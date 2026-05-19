"""Standalone job scraping on a given Playwright page.

Designed for parallel execution: each call gets its own ``Page`` instance
within the same ``BrowserContext``, avoiding shared-state races.
"""

from __future__ import annotations

import logging
from typing import Any

from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from linkedin_mcp_server.core.utils import (
    detect_rate_limit,
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


async def scrape_job_on_page(
    page: Page,
    job_id: str,
    *,
    max_scrolls: int = 5,
) -> dict[str, Any]:
    """Navigate to and scrape a single job posting using the given page.

    Mirrors ``LinkedInExtractor.scrape_job`` but is page-scoped so it can
    be called in parallel across multiple pages in the same browser context.

    Args:
        page: A Playwright Page object (must share auth cookies with the
            main browser context).
        job_id: LinkedIn numeric job ID.
        max_scrolls: Maximum scroll passes to trigger lazy content loading.

    Returns:
        Dict with ``url``, ``sections``, and ``section_errors`` keys,
        matching the shape of ``extractor.scrape_job()``.
    """
    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PlaywrightTimeoutError:
        return _error_result(url, job_id, f"Navigation timeout for {url}")
    except Exception as e:
        return _error_result(url, job_id, f"Navigation failed: {e}")

    try:
        extracted = await _extract_job_page(page, url, max_scrolls=max_scrolls)
    except Exception as e:
        return _error_result(url, job_id, f"Extraction failed: {e}")

    sections: dict[str, str] = {}
    section_errors: dict[str, dict[str, Any]] = {}

    if extracted.text and extracted.text != _RATE_LIMITED_MSG:
        sections["job_posting"] = extracted.text
    elif extracted.error:
        section_errors["job_posting"] = extracted.error

    result: dict[str, Any] = {"url": url, "sections": sections}
    if section_errors:
        result["section_errors"] = section_errors

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

    # Wait for job content to hydrate
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

    # Scroll to trigger lazy loading
    await scroll_to_bottom(page, pause_time=0.5, max_scrolls=max_scrolls)

    # Extract text from main content area
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
