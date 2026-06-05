"""Standalone company-posts page scraping on a given Playwright page."""

from __future__ import annotations

import logging
from typing import Any

from patchright.async_api import Page

from linkedin_mcp_server.tools._common import goto_and_check

logger = logging.getLogger(__name__)


async def scrape_company_posts_page(
    page: Page,
    company_slug: str,
) -> dict[str, Any]:
    """Navigate to a company's posts page and extract raw text.

    Args:
        page: Playwright Page.
        company_slug: LinkedIn company slug (e.g. "docker").

    Returns:
        Dict with ``sections`` (key "posts") and ``url`` keys.
    """
    url = f"https://www.linkedin.com/company/{company_slug}/posts/"
    await goto_and_check(page, url)
    try:
        await page.wait_for_selector("main", timeout=5000)
    except Exception:
        pass
    text = await page.locator("body").inner_text(timeout=3000)
    return {"sections": {"posts": text}, "url": url}
