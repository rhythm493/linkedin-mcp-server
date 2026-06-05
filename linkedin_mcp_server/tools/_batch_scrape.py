"""Shared batch job-scraping orchestration for parallel execution.

Each job gets its own page within the same browser context so auth
cookies are shared without state races.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from linkedin_mcp_server.tools import _job_scrape

logger = logging.getLogger(__name__)


async def batch_scrape_jobs(
    context: Any,
    job_ids: list[str],
    *,
    max_concurrency: int = 10,
) -> list[dict]:
    """Scrape multiple job postings in parallel.

    Args:
        context: Playwright BrowserContext (shared auth with main page).
        job_ids: LinkedIn numeric job ID strings.
        max_concurrency: Max simultaneous pages (default 10).

    Returns:
        List of per-job result dicts in the same order as *job_ids*,
        each with ``url``, ``sections``, optionally ``section_errors``,
        and ``job_id`` set.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _scrape_one(jid: str) -> dict:
        async with semaphore:
            page = await context.new_page()
            try:
                return await _job_scrape.scrape_job_on_page(page, jid)
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

    return all_jobs
