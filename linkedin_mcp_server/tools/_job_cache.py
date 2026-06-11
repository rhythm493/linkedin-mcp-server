"""Persistent SQLite-backed cache for job details with configurable TTL.

Stores scraped job detail results so repeated access (e.g. agent fetches job
details, then later exports them to a database) avoids re-fetching from LinkedIn.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from linkedin_mcp_server.config import get_config

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 7
_CACHE_FILENAME = "job-cache.db"

_ttl_days: int = DEFAULT_TTL_DAYS  # modifiable via set_default_ttl()


def set_default_ttl(days: int) -> None:
    global _ttl_days
    _ttl_days = days


def _get_cache_path() -> Path:
    profile_dir = Path(get_config().browser.user_data_dir).expanduser().resolve()
    return profile_dir.parent / _CACHE_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobCache:
    """SQLite-backed persistent cache for job detail results.

    Each entry stores the full result dict from ``scrape_job_on_page``
    keyed by LinkedIn numeric job ID. Entries expire after *ttl_days*
    and are lazily evicted on read.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        if str(self.db_path) != ":memory:":
            Path(str(self.db_path)).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS job_cache (
                    job_id TEXT PRIMARY KEY,
                    result TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )"""
            )
            conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT result, expires_at FROM job_cache WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        result_json, expires_at = row
        if expires_at < _now_iso():
            self._delete(job_id)
            return None
        return json.loads(result_json)

    def get_many(self, job_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not job_ids:
            return {}
        placeholders = ",".join("?" for _ in job_ids)
        now = _now_iso()
        found: dict[str, dict[str, Any]] = {}
        stale: list[str] = []
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                f"SELECT job_id, result, expires_at FROM job_cache WHERE job_id IN ({placeholders})",
                job_ids,
            ).fetchall()
        for jid, result_json, expires_at in rows:
            if expires_at >= now:
                found[jid] = json.loads(result_json)
            else:
                stale.append(jid)
        if stale:
            self._delete_many(stale)
        return found

    def set(
        self, job_id: str, result: dict[str, Any], ttl_days: int | None = None
    ) -> None:
        if ttl_days is None:
            ttl_days = _ttl_days
        fetched_at = _now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO job_cache (job_id, result, fetched_at, expires_at) VALUES (?, ?, ?, ?)",
                (job_id, json.dumps(result), fetched_at, expires_at),
            )
            conn.commit()

    def invalidate(self, job_id: str) -> None:
        self._delete(job_id)

    def clear_expired(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM job_cache WHERE expires_at < ?", (_now_iso(),))
            conn.commit()

    def clear_all(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM job_cache")
            conn.commit()

    def _delete(self, job_id: str) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM job_cache WHERE job_id = ?", (job_id,))
            conn.commit()

    def _delete_many(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        placeholders = ",".join("?" for _ in job_ids)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                f"DELETE FROM job_cache WHERE job_id IN ({placeholders})",
                job_ids,
            )
            conn.commit()


_cache_instance: JobCache | None = None


def get_job_cache() -> JobCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = JobCache(_get_cache_path())
    return _cache_instance


def reset_job_cache() -> None:
    global _cache_instance
    _cache_instance = None
