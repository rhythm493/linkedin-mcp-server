"""Standalone job scraping on a given Playwright page.

Designed for parallel execution: each call gets its own ``Page`` instance
within the same ``BrowserContext``, avoiding shared-state races.

This is the single source of truth for job scraping — both single and
batch MCP tools delegate here rather than to ``LinkedInExtractor.scrape_job``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from linkedin_mcp_server.core.auth import detect_auth_barrier_quick
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.tools._job_cache import DEFAULT_TTL_DAYS, get_job_cache
from linkedin_mcp_server.core.utils import (
    detect_rate_limit,
    expand_collapsible_sections,
    handle_modal_close,
    scroll_to_bottom,
)
from linkedin_mcp_server.scraping.extractor import (
    ExtractedSection,
    _RATE_LIMITED_MSG,
    _filter_linkedin_noise_lines,
    _truncate_linkedin_noise,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_RETRY_DELAY = 5.0


async def scrape_job_on_page(
    page: Page,
    job_id: str,
    *,
    max_scrolls: int = 5,
    check_auth: bool = True,
) -> dict[str, Any]:
    """Navigate to and scrape a single job posting using the given page.

    This is the single source of truth for all job-detail scraping.
    Both the ``get_job_details`` MCP tool and ``batch_scrape_jobs``
    delegate here.

    When *check_auth* is ``True`` (default), raises
    ``AuthenticationError`` if LinkedIn redirects to a sign-in page.
    Set to ``False`` for batch scraping where the context is pre-authenticated.

    Args:
        page: A Playwright Page object (must share auth cookies with the
            main browser context).
        job_id: LinkedIn numeric job ID.
        max_scrolls: Maximum scroll passes to trigger lazy content loading.
        check_auth: Whether to check for auth barriers after navigation.

    Returns:
        Dict with ``url``, ``sections``, and ``section_errors`` keys.
    """
    cached = get_job_cache().get(job_id)
    if cached is not None:
        logger.debug(
            "scrape_job_on_page: cache hit for job %s, returning cached result", job_id
        )
        return dict(cached)

    url = f"https://www.linkedin.com/jobs/view/{job_id}/"

    for attempt in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError:
            return _error_result(url, job_id, f"Navigation timeout for {url}")
        except Exception as e:
            return _error_result(url, job_id, f"Navigation failed: {e}")

        if check_auth:
            barrier = await detect_auth_barrier_quick(page)
            if barrier:
                raise AuthenticationError(
                    "LinkedIn requires interactive re-authentication. "
                    "Run with --login and complete the account selection/sign-in flow."
                )

        try:
            extracted = await _extract_job_page(page, url, max_scrolls=max_scrolls)
        except Exception as e:
            return _error_result(url, job_id, f"Extraction failed: {e}")

        if extracted.text == _RATE_LIMITED_MSG and attempt == 0:
            logger.info(
                "Retrying job %s after %.0fs backoff", url, _RATE_LIMIT_RETRY_DELAY
            )
            await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY)
            continue

        break

    sections: dict[str, str] = {}
    section_errors: dict[str, dict[str, Any]] = {}

    if extracted.text and extracted.text != _RATE_LIMITED_MSG:
        sections["job_posting"] = extracted.text
    elif extracted.error:
        section_errors["job_posting"] = extracted.error

    result: dict[str, Any] = {"url": url, "sections": sections}
    if section_errors:
        result["section_errors"] = section_errors

    if sections:
        cached_result: dict[str, Any] = {**result, "job_id": job_id}
        get_job_cache().set(job_id, cached_result, ttl_days=DEFAULT_TTL_DAYS)

    return result


async def _extract_job_page(
    page: Page, url: str, *, max_scrolls: int
) -> ExtractedSection:
    """Post-navigation extraction pipeline for a job detail page."""
    await detect_rate_limit(page)

    # Wait for main content to render
    try:
        await page.wait_for_selector("main", timeout=5000)
    except PlaywrightTimeoutError:
        logger.debug("No <main> element found on %s", url)

    # Dismiss any modals blocking content
    await handle_modal_close(page)

    # Wait for job content to hydrate (SPA renders <main> before API data)
    try:
        await page.wait_for_function(
            """() => {
                const main = document.querySelector('main');
                if (!main) return false;
                return main.innerText.length > 100;
            }""",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        logger.debug("Job content did not hydrate on %s", url)

    # Expand collapsed sections (Show more buttons) before extracting text
    await expand_collapsible_sections(page)

    # Scroll to trigger lazy loading
    await scroll_to_bottom(page, pause_time=0.5, max_scrolls=max_scrolls)

    # Extract from <main> via ARIA landmark — excludes sidebar/footer before filtering
    core = page.locator("section[aria-label='Primary content']")
    if await core.count() > 0:
        raw = await core.inner_text(timeout=10000)
    else:
        raw = await page.locator("main").inner_text(timeout=10000)
    if not isinstance(raw, str):
        raw = ""

    if not raw:
        return ExtractedSection(text="", references=[])

    truncated = _truncate_linkedin_noise(raw)
    if not truncated and raw.strip():
        logger.warning("Job page %s returned only LinkedIn chrome", url)
        return ExtractedSection(text=_RATE_LIMITED_MSG, references=[])

    cleaned = _filter_linkedin_noise_lines(truncated)
    return ExtractedSection(text=cleaned, references=[])


def _error_result(url: str, job_id: str, error: str) -> dict[str, Any]:
    return {
        "url": url,
        "sections": {},
        "section_errors": {"job_posting": {"error": error}},
    }
