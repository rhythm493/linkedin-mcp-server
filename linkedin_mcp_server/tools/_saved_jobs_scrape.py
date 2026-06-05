"""Standalone saved-jobs page scraping on a given Playwright page.

Supports single-page and multi-page (pagination) modes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from patchright.async_api import Page

from linkedin_mcp_server.tools import _common

logger = logging.getLogger(__name__)

_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")


def _extract_job_id(job_url: str | None) -> str | None:
    if not job_url:
        return None
    match = _JOB_ID_RE.search(job_url)
    return match.group(1) if match else None


def _parse_saved_job_card_text(
    text: str, *, job_url: str | None
) -> dict[str, Any] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    title = lines[0]
    company_idx = 1
    if lines[1].startswith(", Verified"):
        company_idx = 2
    company = lines[company_idx] if company_idx < len(lines) else None
    location_idx = company_idx + 1
    location = lines[location_idx] if location_idx < len(lines) else None
    posting_date = None
    for line in lines[location_idx:]:
        if "ago" in line.lower() or re.match(r"\d{4}-\d{2}-\d{2}$", line):
            posting_date = line
            break
    return {
        "title": title,
        "company": company,
        "location": location,
        "posting_date": posting_date,
        "job_id": _extract_job_id(job_url),
        "job_url": job_url,
    }


async def parse_saved_jobs_page(
    page: Page,
    url: str,
    *,
    limit: int | None = None,
    seen_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Parse job cards from a single saved-jobs page.

    Args:
        page: Playwright Page already navigated to a saved-jobs URL.
        url: The full LinkedIn saved-jobs URL (used for goto).
        limit: Max jobs to return from this page (None = all).
        seen_ids: Set of already-seen job IDs for dedup.

    Returns:
        (jobs, seen_ids) where *jobs* is the list of parsed card dicts
        and *seen_ids* is the dedup set (newly populated if not passed in).
    """
    if seen_ids is None:
        seen_ids = set()

    await _common.goto_and_check(page, url)
    await asyncio.sleep(2)

    rows = page.locator("li, article, .job-card-container, [data-job-id]")
    total_rows = await rows.count()
    jobs: list[dict[str, Any]] = []

    for idx in range(total_rows):
        row = rows.nth(idx)
        anchor = row.locator("a[href*='/jobs/view/']").first
        href = await anchor.get_attribute("href") if await anchor.count() > 0 else None
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
        jobs.append(card)
        if limit is not None and len(jobs) >= limit:
            break

    return jobs, seen_ids


async def scrape_saved_jobs(
    page: Page,
    *,
    max_pages: int = 5,
) -> dict[str, Any]:
    """Scrape all saved jobs across multiple paginated pages.

    Args:
        page: Playwright Page.
        max_pages: Maximum number of result pages to fetch (default 5).

    Returns:
        Dict with ``jobs``, ``sections``, ``url``, and ``pages_fetched`` keys.
    """
    all_jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    page_num = 1
    has_next = True

    while has_next:
        if page_num > max_pages:
            logger.debug("Reached max_pages=%d, stopping", max_pages)
            break

        start = (page_num - 1) * 10
        url = f"https://www.linkedin.com/my-items/saved-jobs/?cardType=SAVED&start={start}"

        logger.debug("Navigating to saved jobs page %d: %s", page_num, url)
        page_jobs, seen_ids = await parse_saved_jobs_page(page, url, seen_ids=seen_ids)
        logger.debug("Page %d parsed %d new jobs", page_num, len(page_jobs))
        all_jobs.extend(page_jobs)

        try:
            next_btn = page.locator(
                'button:has-text("Next"), a:has-text("Next"), button[aria-label*="next"], a[aria-label*="next"]'
            )
            has_next = await next_btn.count() > 0
            logger.debug("Page %d has_next button check: %s", page_num, has_next)
        except Exception:
            has_next = len(page_jobs) > 0

        page_num += 1

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
