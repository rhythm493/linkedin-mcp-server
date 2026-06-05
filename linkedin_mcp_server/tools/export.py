"""
Export tools: export LinkedIn data directly to SQLite and query local databases.

Avoids context pollution by scraping → writing to DB on the server side.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Literal


from fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# ── Response types ────────────────────────────────────────────────────────


class ExportResult(BaseModel):
    source: str  # "linkedin" | "cache"
    rows_saved: int
    table: str
    columns: list[str]
    cached_at: str | None = None


class SqlResult(BaseModel):
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    affected_rows: int | None = None
    duration_ms: int


class ColumnInfo(BaseModel):
    cid: int
    name: str
    type: str
    notnull: int
    default_value: str | None
    pk: int


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]


class ListTablesResult(BaseModel):
    tables: list[TableInfo]


# ── Tool name constants ──────────────────────────────────────────────────

VALID_TOOL_NAMES = frozenset(
    {
        "get_saved_jobs",
        "get_job_recommendations",
        "search_jobs",
        "get_job_details",
        "get_person_profile",
        "get_my_profile",
        "get_company_profile",
        "get_company_posts",
        "get_company_people",
        "get_feed",
        "get_inbox",
        "get_conversation",
        "get_pending_invitations",
    }
)

# ── Helpers ──────────────────────────────────────────────────────────────

_CACHE_TABLE = "_cache"

_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")


def _resolve_db_path(db_path: str) -> str:
    """Resolve db_path to absolute path.

    If relative, resolves against CWD. Absolute paths are accepted as-is.
    """
    if os.path.isabs(db_path):
        return os.path.normpath(db_path)
    return os.path.normpath(os.path.join(os.getcwd(), db_path))


def _params_hash(params: dict) -> str:
    """Deterministic hash of tool params for cache key."""
    raw = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _ensure_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} (
            tool_name TEXT,
            params_hash TEXT,
            table_name TEXT,
            fetched_at TEXT,
            row_count INTEGER,
            PRIMARY KEY (tool_name, params_hash)
        )"""
    )
    conn.commit()


def _check_cache(
    conn: sqlite3.Connection, tool_name: str, params: dict, table: str
) -> dict | None:
    """Return cache row if exists and table is still present."""
    _ensure_cache(conn)
    ph = _params_hash(params)
    cur = conn.execute(
        f"SELECT fetched_at, row_count FROM {_CACHE_TABLE} WHERE tool_name = ? AND params_hash = ?",
        (tool_name, ph),
    )
    row = cur.fetchone()
    if row is None:
        return None
    # Verify table exists
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    if table not in tables:
        return None
    return {"fetched_at": row[0], "row_count": row[1]}


def _update_cache(
    conn: sqlite3.Connection,
    tool_name: str,
    params: dict,
    table: str,
    row_count: int,
) -> None:
    _ensure_cache(conn)
    ph = _params_hash(params)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        f"INSERT OR REPLACE INTO {_CACHE_TABLE} (tool_name, params_hash, table_name, fetched_at, row_count) VALUES (?,?,?,?,?)",
        (tool_name, ph, table, now, row_count),
    )
    conn.commit()


def _infer_sqlite_type(value: Any) -> str:
    if value is None:
        return "TEXT"
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    return "TEXT"


def _create_table(
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    *,
    mode: Literal["replace", "append"] = "replace",
) -> list[str]:
    """CREATE TABLE from first row's keys. Returns column names.

    Args:
        mode: ``"replace"`` drops and recreates the table (default).
              ``"append"`` preserves existing data and adds missing columns.
    """
    cols = list(row.keys())
    col_defs = ", ".join(f'"{c}" {_infer_sqlite_type(row[c])}' for c in cols)

    if mode == "replace":
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" ({col_defs})')
    else:
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({col_defs})')
        existing = {
            r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        for c in cols:
            if c not in existing:
                conn.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN "{c}" {_infer_sqlite_type(row[c])}'
                )

    conn.commit()
    return cols


def _insert_rows(
    conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]
) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(f'"{c}"' for c in cols)
    sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'
    values = [tuple(row.get(c) for c in cols) for row in rows]
    conn.executemany(sql, values)
    conn.commit()
    return len(values)


def _normalize_saved_jobs(result: dict) -> list[dict]:
    rows = result.get("jobs", [])
    return [
        {
            "title": r.get("title"),
            "company": r.get("company"),
            "location": r.get("location"),
            "posting_date": r.get("posting_date"),
            "job_id": r.get("job_id"),
            "job_url": r.get("job_url"),
            "_exported_at": datetime.now(timezone.utc).isoformat(),
        }
        for r in rows
    ]


def _normalize_recommendations(result: dict) -> list[dict]:
    rows = result.get("jobs", [])
    return [
        {
            "title": r.get("title"),
            "company": r.get("company"),
            "location": r.get("location"),
            "job_id": r.get("job_id"),
            "job_url": r.get("job_url"),
            "_exported_at": datetime.now(timezone.utc).isoformat(),
        }
        for r in rows
    ]


def _normalize_search_jobs(result: dict) -> list[dict]:
    job_ids = result.get("job_ids", [])
    return [
        {
            "job_id": jid,
            "keywords": None,
            "searched_at": datetime.now(timezone.utc).isoformat(),
        }
        for jid in job_ids
    ]


def _normalize_sections(result: dict, tool_name: str) -> list[dict]:
    """Store raw section-based results as rows."""
    sections = result.get("sections", {})
    rows = []
    for section_name, content in sections.items():
        rows.append(
            {
                "section_name": section_name,
                "content": content,
                "tool": tool_name,
                "url": result.get("url"),
                "_exported_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return rows


def _normalize_job_details(result: dict) -> list[dict]:
    """Normalize job details result (single or batch)."""
    # Check if this is a batch result
    if "jobs" in result:
        return _normalize_job_details_batch(result)
    return _normalize_sections(result, "get_job_details")


def _normalize_job_details_batch(result: dict) -> list[dict]:
    """Normalize batch job details results."""
    jobs = result.get("jobs", [])
    rows = []
    for job in jobs:
        sections = job.get("sections", {})
        for section_name, content in sections.items():
            row = {
                "job_id": job.get("job_id"),
                "url": job.get("url"),
                "section_name": section_name,
                "content": content,
                "_exported_at": datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)
        if not sections:
            # Store error rows too so user knows what failed
            errors = job.get("section_errors", {})
            for section_name, error_info in errors.items():
                rows.append(
                    {
                        "job_id": job.get("job_id"),
                        "url": job.get("url"),
                        "section_name": section_name,
                        "content": None,
                        "error": json.dumps(error_info) if error_info else None,
                        "_exported_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    return rows


def _normalize_person_profile(result: dict) -> list[dict]:
    return _normalize_sections(result, "get_person_profile")


def _normalize_company_profile(result: dict) -> list[dict]:
    return _normalize_sections(result, "get_company_profile")


def _normalize_company_posts(result: dict) -> list[dict]:
    return _normalize_sections(result, "get_company_posts")


def _normalize_company_people(result: dict) -> list[dict]:
    rows = result.get("people", [])
    return [
        {
            "name": r.get("name"),
            "headline": r.get("headline"),
            "location": r.get("location"),
            "connection_degree": r.get("connection_degree"),
            "shared_connections": r.get("shared_connections"),
            "profile_url": r.get("profile_url"),
            "_exported_at": datetime.now(timezone.utc).isoformat(),
        }
        for r in rows
    ]


def _normalize_feed(result: dict) -> list[dict]:
    return _normalize_sections(result, "get_feed")


def _normalize_inbox(result: dict) -> list[dict]:
    return _normalize_sections(result, "get_inbox")


def _normalize_conversation(result: dict) -> list[dict]:
    return _normalize_sections(result, "get_conversation")


def _normalize_pending_invitations(result: dict) -> list[dict]:
    invitations = result.get("invitations", [])
    return [
        {
            "from_name": inv.get("name"),
            "from_headline": inv.get("headline"),
            "from_profile_url": inv.get("profile_url"),
            "mutual_connections": inv.get("mutual_connections"),
            "_exported_at": datetime.now(timezone.utc).isoformat(),
        }
        for inv in invitations
    ]


# Dispatch: tool_name → (fetch_fn, normalize_fn)
# fetch_fn receives an extractor + kwargs and returns raw data
# normalize_fn converts raw data to list[dict]
_NORMALIZERS: dict[str, Callable[..., list[dict]]] = {
    "get_saved_jobs": _normalize_saved_jobs,
    "get_job_recommendations": _normalize_recommendations,
    "search_jobs": _normalize_search_jobs,
    "get_job_details": _normalize_job_details,
    "get_person_profile": _normalize_person_profile,
    "get_my_profile": _normalize_person_profile,
    "get_company_profile": _normalize_company_profile,
    "get_company_posts": _normalize_company_posts,
    "get_company_people": _normalize_company_people,
    "get_feed": _normalize_feed,
    "get_inbox": _normalize_inbox,
    "get_conversation": _normalize_conversation,
    "get_pending_invitations": _normalize_pending_invitations,
}


# ── Extractor method dispatch ────────────────────────────────────────────

# Tools handled by extractor methods — (method_name, param_keys)
_EXTRACTOR_METHODS: dict[str, tuple[str, list[str]]] = {
    "search_jobs": (
        "search_jobs",
        [
            "keywords",
            "location",
            "max_pages",
            "date_posted",
            "job_type",
            "experience_level",
            "work_type",
            "easy_apply",
            "sort_by",
        ],
    ),
    "get_job_details": ("scrape_job", ["job_id"]),
    "get_person_profile": (
        "scrape_person",
        ["linkedin_username", "sections", "max_scrolls", "connection_filter"],
    ),
    "get_my_profile": ("get_my_profile", ["sections", "max_scrolls"]),
    "get_company_profile": ("scrape_company", ["company_slug", "sections"]),
    "get_feed": ("extract_feed", ["num_posts"]),
    "get_inbox": ("get_inbox", ["limit"]),
    "get_conversation": (
        "get_conversation",
        ["linkedin_username", "thread_id", "index"],
    ),
}


def _parse_job_ids(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return raw
    return [jid.strip() for jid in raw.split(",") if jid.strip()]


async def _fetch_internal(
    tool_name: str, extractor: Any, tool_params: dict, ctx: Any
) -> dict:
    """Dispatch a tool to its scraping implementation.

    Supports extractor methods, batch job scraping, and DOM-based kernels.
    """
    page = extractor.page

    # Batch job_details — parallel execution for multiple job_ids
    if tool_name == "get_job_details" and "job_ids" in tool_params:
        from linkedin_mcp_server.tools._batch_scrape import batch_scrape_jobs

        job_ids = _parse_job_ids(tool_params["job_ids"])
        logger.debug("Batch job_details: fetching %d jobs in parallel", len(job_ids))
        all_jobs = await batch_scrape_jobs(page.context, job_ids)
        logger.debug(
            "Batch job_details complete: %d jobs, %d with content",
            len(all_jobs),
            sum(1 for j in all_jobs if j.get("sections")),
        )
        return {"jobs": all_jobs, "sections": {}, "url": "batch://job_details"}

    # Extractor-method tools
    if tool_name in _EXTRACTOR_METHODS:
        method_name, param_keys = _EXTRACTOR_METHODS[tool_name]
        params = {k: tool_params.get(k) for k in param_keys if k in tool_params}
        method = getattr(extractor, method_name, None)
        if method is not None:
            return await method(**params)

    # DOM-based tools via extracted kernels
    if tool_name == "get_saved_jobs":
        from linkedin_mcp_server.tools._saved_jobs_scrape import scrape_saved_jobs

        max_pages = tool_params.get("max_pages", 5)
        return await scrape_saved_jobs(page, max_pages=max_pages)

    if tool_name == "get_job_recommendations":
        from linkedin_mcp_server.tools._recommendations_scrape import (
            parse_recommendations_page,
        )

        jobs = await parse_recommendations_page(page)
        return {"jobs": jobs, "sections": {}, "url": "https://www.linkedin.com/jobs/"}

    if tool_name == "get_company_people":
        from linkedin_mcp_server.tools._company_people_scrape import (
            parse_company_people_page,
        )

        company_name = tool_params.get("company_name", "")
        limit = tool_params.get("limit", 25)
        people = await parse_company_people_page(page, company_name, limit=limit)
        slug = company_name.strip().lower().replace(" ", "-")
        return {
            "people": people,
            "sections": {},
            "url": f"https://www.linkedin.com/company/{slug}/people/",
        }

    if tool_name == "get_pending_invitations":
        from linkedin_mcp_server.tools._pending_invitations_scrape import (
            parse_pending_invitations_page,
        )

        invitations = await parse_pending_invitations_page(page)
        return {
            "invitations": invitations,
            "sections": {},
            "url": "https://www.linkedin.com/mynetwork/invitation-manager/",
        }

    if tool_name == "get_company_posts":
        from linkedin_mcp_server.tools._company_posts_scrape import (
            scrape_company_posts_page,
        )

        return await scrape_company_posts_page(
            page, tool_params.get("company_slug", "")
        )

    raise ValueError(f"Unsupported tool_name for export: {tool_name}")


def register_export_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Export to Database",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    )
    async def export_to_db(
        tool_name: Annotated[
            str,
            Field(
                description="Name of a LinkedIn tool to export results from.",
                json_schema_extra={
                    "enum": sorted(VALID_TOOL_NAMES),
                },
            ),
        ],
        db_path: Annotated[
            str,
            Field(
                description="Path to a SQLite file, relative to working directory.",
            ),
        ],
        table_name: Annotated[
            str,
            Field(
                description="Table name to create or replace in the database.",
            ),
        ],
        tool_params: Annotated[
            dict,
            Field(
                default_factory=dict,
                description='Parameters to pass to the LinkedIn tool. Examples: {"keywords": "python"} for search_jobs, {"job_ids": ["4404087079", ...]} for batch job details.',
            ),
        ],
        refresh: Annotated[
            bool,
            Field(
                default=False,
                description="If True, re-scrape from LinkedIn. If False and cached data exists, skip the scrape.",
            ),
        ],
        mode: Annotated[
            Literal["replace", "append"],
            Field(
                default="replace",
                description='"replace" drops and recreates the table. "append" preserves existing data and adds new rows.',
            ),
        ] = "replace",
        ctx: Context | None = None,
    ) -> ExportResult:
        """Export LinkedIn data directly to a local SQLite database.

        Scrapes data and writes it to SQLite. Returns only a summary —
        no raw data enters the LLM context window. Supports caching: if
        ``refresh=False`` and cached data exists for the same tool/params,
        returns the cached result without hitting LinkedIn.

        Use ``mode="append"`` to add rows to an existing table without
        destroying prior data.
        """
        if tool_name not in VALID_TOOL_NAMES:
            raise ValueError(
                f"Unknown tool_name '{tool_name}'. "
                f"Valid options: {', '.join(sorted(VALID_TOOL_NAMES))}"
            )
        db = _resolve_db_path(db_path)

        logger.debug(
            "export_to_db called: tool=%s, db=%s, table=%s, refresh=%s",
            tool_name,
            db,
            table_name,
            refresh,
        )

        # Check cache
        with sqlite3.connect(db) as conn:
            cached = _check_cache(conn, tool_name, tool_params, table_name)
            if cached and not refresh:
                logger.debug("Cache hit for %s, returning cached result", tool_name)
                return ExportResult(
                    source="cache",
                    rows_saved=cached["row_count"],
                    table=table_name,
                    columns=[],
                    cached_at=cached["fetched_at"],
                )

            if ctx is None:
                logger.error("Context is None but cache miss requires scraping")
                raise RuntimeError("Context required for scraping when cache miss")

            # Import scraper internals
            logger.debug("Cache miss, fetching fresh data for %s", tool_name)
            from linkedin_mcp_server.dependencies import get_ready_extractor

            logger.debug("Getting ready extractor for export_to_db:%s", tool_name)
            extractor = await get_ready_extractor(
                ctx, tool_name=f"export_to_db:{tool_name}"
            )
            logger.debug("Extractor obtained successfully")

            # Call the right scraper logic
            logger.debug(
                "Calling _fetch_internal for %s with params: %s", tool_name, tool_params
            )
            try:
                raw_result = await _fetch_internal(
                    tool_name, extractor, tool_params, ctx
                )
            except Exception as e:
                logger.error(
                    "Scraping failed for %s: %s: %s",
                    tool_name,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                raise
            logger.debug(
                "Raw result received: %d keys: %s",
                len(raw_result),
                list(raw_result.keys()),
            )

            # Normalize to rows
            normalizer = _NORMALIZERS[tool_name]
            rows = normalizer(raw_result)
            logger.debug("Normalized %d rows for export", len(rows))

            # Write to DB
            if rows:
                logger.debug(
                    "Creating table %s and inserting %d rows", table_name, len(rows)
                )
                columns = _create_table(conn, table_name, rows[0], mode=mode)
                count = _insert_rows(conn, table_name, rows)
                logger.debug("Inserted %d rows into %s", count, table_name)
            else:
                columns = []
                count = 0
                logger.warning("No rows to export for %s", tool_name)

            _update_cache(conn, tool_name, tool_params, table_name, count)
            logger.debug("Cache updated for %s with %d rows", tool_name, count)

            return ExportResult(
                source="linkedin",
                rows_saved=count,
                table=table_name,
                columns=columns,
            )

    @mcp.tool(
        timeout=tool_timeout,
        title="Run SQL Query",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    )
    async def run_sql(
        db_path: Annotated[
            str,
            Field(
                description="Path to a SQLite file, relative to working directory.",
            ),
        ],
        sql: Annotated[
            str,
            Field(
                description="SQL query to execute (SELECT, INSERT, UPDATE, DELETE, ATTACH, etc.).",
            ),
        ],
        params: list[Any] | None = None,
    ) -> SqlResult:
        """Execute a SQL query on a local SQLite database.

        Supports SELECT, INSERT, UPDATE, DELETE, ATTACH, CREATE, etc.
        For SELECT queries, returns rows as JSON. For DML, returns
        affected row count. Cross-database queries via ATTACH are
        supported (e.g. ``ATTACH 'other.db' AS o; SELECT ...``).
        """
        db = _resolve_db_path(db_path)
        start = time.monotonic()

        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row

            statements = [s.strip() for s in sql.split(";") if s.strip()]
            cur = None
            for idx, stmt in enumerate(statements):
                stmt_params = params if idx == len(statements) - 1 and params else []
                cur = conn.execute(stmt, stmt_params)

            conn.commit()

            if cur and cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = [dict(r) for r in cur.fetchall()]
            else:
                columns = []
                rows = []

            affected = cur.rowcount if cur else 0

        elapsed = int((time.monotonic() - start) * 1000)

        return SqlResult(
            rows=rows,
            columns=columns,
            row_count=len(rows),
            affected_rows=affected if affected >= 0 else None,
            duration_ms=elapsed,
        )

    @mcp.tool(
        timeout=tool_timeout,
        title="List Database Tables",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    )
    async def list_tables(
        db_path: Annotated[
            str,
            Field(
                description="Path to a SQLite file, relative to working directory.",
            ),
        ],
    ) -> ListTablesResult:
        """List all tables and their schemas in a local SQLite database."""
        db = _resolve_db_path(db_path)
        tables: list[TableInfo] = []

        with sqlite3.connect(db) as conn:
            table_names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name != ? ORDER BY name",
                    (_CACHE_TABLE,),
                ).fetchall()
            ]
            for name in table_names:
                cols = []
                for row in conn.execute(f'PRAGMA table_info("{name}")').fetchall():
                    cols.append(
                        ColumnInfo(
                            cid=row[0],
                            name=row[1],
                            type=row[2],
                            notnull=row[3],
                            default_value=str(row[4]) if row[4] is not None else None,
                            pk=row[5],
                        )
                    )
                tables.append(TableInfo(name=name, columns=cols))

        return ListTablesResult(tables=tables)
