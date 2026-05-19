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
from typing import Annotated, Any, Callable

import asyncio

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
    conn: sqlite3.Connection, table: str, row: dict[str, Any]
) -> list[str]:
    """CREATE TABLE from first row's keys. Returns column names."""
    cols = list(row.keys())
    col_defs = ", ".join(f'"{c}" {_infer_sqlite_type(row[c])}' for c in cols)
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(f'CREATE TABLE "{table}" ({col_defs})')
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


def _build_extractor_params(tool_name: str, tool_params: dict) -> dict:
    """Map tool params to the corresponding extractor method kwargs."""
    mapping: dict[str, list[str]] = {
        "search_jobs": [
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
        "get_job_details": ["job_id"],
        "get_person_profile": [
            "linkedin_username",
            "sections",
            "max_scrolls",
            "connection_filter",
        ],
        "get_my_profile": ["sections", "max_scrolls"],
        "get_company_profile": ["company_slug", "sections"],
        "get_company_posts": ["company_slug", "max_scrolls"],
        "get_company_people": [
            "company_name",
            "title_keyword",
            "limit",
        ],
        "get_feed": ["num_posts"],
        "get_inbox": ["limit"],
        "get_conversation": ["linkedin_username", "thread_id", "index"],
        "get_saved_jobs": ["limit", "page", "next_cursor"],
    }
    allowed = mapping.get(tool_name, [])
    return {k: v for k, v in tool_params.items() if k in allowed}


async def _fetch_internal(
    tool_name: str, extractor: Any, tool_params: dict, ctx: Any
) -> dict:
    """Call the correct scraper logic for a given tool_name.

    Uses extractor methods where available, otherwise does direct DOM access.
    """
    from linkedin_mcp_server.tools._common import goto_and_check

    # Tools that map directly to extractor methods
    extractor_methods: dict[str, tuple[str, dict]] = {
        "search_jobs": ("search_jobs", _build_extractor_params(tool_name, tool_params)),
        "get_job_details": (
            "scrape_job",
            _build_extractor_params(tool_name, tool_params),
        ),
        "get_person_profile": (
            "scrape_person",
            _build_extractor_params(tool_name, tool_params),
        ),
        "get_my_profile": (
            "get_my_profile",
            _build_extractor_params(tool_name, tool_params),
        ),
        "get_company_profile": (
            "scrape_company",
            _build_extractor_params(tool_name, tool_params),
        ),
        "get_feed": ("extract_feed", _build_extractor_params(tool_name, tool_params)),
        "get_inbox": ("get_inbox", _build_extractor_params(tool_name, tool_params)),
        "get_conversation": (
            "get_conversation",
            _build_extractor_params(tool_name, tool_params),
        ),
    }

    # Batch mode: get_job_details with job_ids list — parallel execution
    if tool_name == "get_job_details" and "job_ids" in tool_params:
        job_ids = tool_params["job_ids"]
        if isinstance(job_ids, str):
            job_ids = [jid.strip() for jid in job_ids.split(",") if jid.strip()]

        logger.debug("Batch job_details: fetching %d jobs in parallel", len(job_ids))

        from linkedin_mcp_server.tools._job_scrape import scrape_job_on_page

        context = extractor.page.context
        semaphore = asyncio.Semaphore(10)  # max 10 concurrent pages

        async def _scrape_one(jid: str) -> dict:
            async with semaphore:
                page = await context.new_page()
                try:
                    return await scrape_job_on_page(page, jid)
                except Exception as e:
                    logger.warning("Failed to scrape job %s: %s", jid, e)
                    return {
                        "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                        "sections": {},
                        "section_errors": {"job_posting": {"error": str(e)}},
                    }
                finally:
                    await page.close()

        tasks = [_scrape_one(jid) for jid in job_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_jobs: list[dict] = []
        for jid, result in zip(job_ids, results):
            if isinstance(result, Exception):
                all_jobs.append(
                    {
                        "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                        "sections": {},
                        "section_errors": {"job_posting": {"error": str(result)}},
                    }
                )
            elif isinstance(result, dict):
                result["job_id"] = jid
                all_jobs.append(result)

        logger.debug(
            "Batch job_details complete: %d jobs fetched, %d with content",
            len(all_jobs),
            sum(1 for j in all_jobs if j.get("sections")),
        )
        return {"jobs": all_jobs, "sections": {}, "url": "batch://job_details"}

    if tool_name in extractor_methods:
        method_name, params = extractor_methods[tool_name]
        method = getattr(extractor, method_name, None)
        if method is not None:
            return await method(**params)

    # DOM-based tools — navigate + parse inline
    page = extractor.page

    if tool_name == "get_saved_jobs":
        from linkedin_mcp_server.tools._common import goto_and_check
        from linkedin_mcp_server.tools.saved_jobs import (
            _parse_saved_job_card_text,
            _extract_job_id,
        )

        logger.debug("Starting saved_jobs multi-page fetch")
        max_pages = tool_params.get("max_pages")
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()
        page_num = 1
        has_next = True

        while has_next:
            if max_pages and page_num > max_pages:
                logger.debug("Reached max_pages=%d, stopping", max_pages)
                break

            # LinkedIn saved jobs displays 10 items per page
            # Use (page_num - 1) * 10 as offset to match UI pagination
            start = (page_num - 1) * 10
            url = f"https://www.linkedin.com/my-items/saved-jobs/?cardType=SAVED&start={start}"

            logger.debug("Navigating to saved jobs page %d: %s", page_num, url)
            await goto_and_check(page, url)
            await asyncio.sleep(2)

            rows = page.locator("li, article, .job-card-container, [data-job-id]")
            total_rows = await rows.count()
            logger.debug("Page %d found %d DOM rows", page_num, total_rows)

            page_jobs = []
            for idx in range(total_rows):
                row = rows.nth(idx)
                anchor = row.locator("a[href*='/jobs/view/']").first
                href = (
                    await anchor.get_attribute("href")
                    if await anchor.count() > 0
                    else None
                )
                if href and href.startswith("/"):
                    href = f"https://www.linkedin.com{href}"
                if not href:
                    continue

                job_id = _extract_job_id(href)
                if job_id and job_id in seen_ids:
                    continue
                if job_id:
                    seen_ids.add(job_id)

                try:
                    text = await row.inner_text(timeout=1000)
                except Exception:
                    continue
                card = _parse_saved_job_card_text(text, job_url=href)
                if card is None:
                    continue
                page_jobs.append(card)

            logger.debug("Page %d parsed %d new jobs", page_num, len(page_jobs))
            all_jobs.extend(page_jobs)

            # LinkedIn paginates by 10 items; check for next button in DOM
            try:
                next_btn = page.locator(
                    'button:has-text("Next"), a:has-text("Next"), button[aria-label*="next"], a[aria-label*="next"]'
                )
                has_next = await next_btn.count() > 0
                logger.debug("Page %d has_next button check: %s", page_num, has_next)
            except Exception:
                has_next = len(page_jobs) > 0

            page_num += 1

            # Safety: stop if no jobs returned (end of data)
            if not page_jobs:
                logger.debug("No more jobs, ending pagination")
                break

        logger.debug(
            "Saved_jobs fetch complete: %d jobs across %d pages",
            len(all_jobs),
            page_num - 1,
        )
        return {
            "jobs": all_jobs,
            "sections": {},
            "url": "https://www.linkedin.com/my-items/saved-jobs/?cardType=SAVED",
            "pages_fetched": page_num - 1,
        }

    if tool_name == "get_job_recommendations":
        await goto_and_check(page, "https://www.linkedin.com/jobs/")
        await asyncio.sleep(2)
        from linkedin_mcp_server.tools.recommendations import (
            _RECOMMENDATION_COMPANY_SELECTORS,
            _RECOMMENDATION_TITLE_SELECTORS,
            _RECOMMENDATION_LOCATION_SELECTORS,
            _RECOMMENDATION_LINK_SELECTORS,
            _first_locator_text,
            _first_locator_href,
            _normalize_job_url,
            _extract_job_id,
            _build_job_result,
        )

        jobs: list[dict] = []
        rows_loc = page.locator(
            ".job-card-container, [data-job-id], article.job-card-list__container"
        )
        for i in range(await rows_loc.count()):
            row = rows_loc.nth(i)
            title = _first_locator_text(row, _RECOMMENDATION_TITLE_SELECTORS)
            company = _first_locator_text(row, _RECOMMENDATION_COMPANY_SELECTORS)
            location = _first_locator_text(row, _RECOMMENDATION_LOCATION_SELECTORS)
            href = _first_locator_href(row, _RECOMMENDATION_LINK_SELECTORS)
            job_url = _normalize_job_url(href)
            job = _build_job_result(
                title, company, location, _extract_job_id(job_url), job_url
            )
            if job:
                jobs.append(job)
        return {"jobs": jobs, "sections": {}, "url": "https://www.linkedin.com/jobs/"}

    if tool_name == "get_company_people":
        company_name = tool_params.get("company_name", "")
        slug = company_name.strip().lower().replace(" ", "-")
        url = f"https://www.linkedin.com/company/{slug}/people/"
        await goto_and_check(page, url)
        from linkedin_mcp_server.tools.people import (
            _parse_person_card_text,
            _normalize_profile_url,
        )

        people: list[dict] = []
        rows_loc = page.locator('a[href*="/in/"], li:has(a[href*="/in/"])')
        limit = max(1, min(int(tool_params.get("limit", 25)), 25))
        for i in range(await rows_loc.count()):
            if len(people) >= limit:
                break
            row = rows_loc.nth(i)
            try:
                link = row.locator('a[href*="/in/"]').first
                if await link.count() == 0:
                    continue
                href = await link.get_attribute("href", timeout=300)
                profile_url = _normalize_profile_url(href)
                text = await row.inner_text(timeout=800)
            except Exception:
                continue
            card = _parse_person_card_text(text, profile_url=profile_url)
            if card:
                people.append(
                    {
                        "name": card.name,
                        "profile_url": card.profile_url,
                        "headline": card.headline,
                        "location": card.location,
                        "connection_degree": card.connection_degree,
                        "shared_connections": card.shared_connections,
                    }
                )
        return {"people": people, "sections": {}, "url": url}

    if tool_name == "get_pending_invitations":
        await goto_and_check(
            page, "https://www.linkedin.com/mynetwork/invitation-manager/"
        )
        await asyncio.sleep(2)
        invitations: list[dict] = []
        rows_loc = page.locator('a[href*="/in/"]')
        total = await rows_loc.count()
        for i in range(min(total, 100)):
            row = rows_loc.nth(i)
            try:
                text = await row.inner_text(timeout=2000)
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                name = lines[0] if lines else ""
                headline = lines[1] if len(lines) > 1 else ""
                href = await row.get_attribute("href")
                if href and href.startswith("/"):
                    href = f"https://www.linkedin.com{href}"
                invitations.append(
                    {
                        "name": name,
                        "profile_url": href,
                        "headline": headline,
                    }
                )
            except Exception:
                continue
        return {
            "invitations": invitations,
            "sections": {},
            "url": "https://www.linkedin.com/mynetwork/invitation-manager/",
        }

    if tool_name == "get_company_posts":
        company_slug = tool_params.get("company_slug", "")
        url = f"https://www.linkedin.com/company/{company_slug}/posts/"
        await goto_and_check(page, url)
        try:
            await page.wait_for_selector("main", timeout=5000)
        except Exception:
            pass
        text = await page.locator("body").inner_text(timeout=3000)
        return {"sections": {"posts": text}, "url": url}

    # Fallback: raise
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
        ctx: Context | None = None,
    ) -> ExportResult:
        """Export LinkedIn data directly to a local SQLite database.

        Scrapes data and writes it to SQLite. Returns only a summary —
        no raw data enters the LLM context window. Supports caching: if
        ``refresh=False`` and cached data exists for the same tool/params,
        returns the cached result without hitting LinkedIn.
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
                columns = _create_table(conn, table_name, rows[0])
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
