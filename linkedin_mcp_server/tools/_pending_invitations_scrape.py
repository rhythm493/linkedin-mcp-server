"""Standalone pending-invitations page scraping on a given Playwright page."""

from __future__ import annotations

import logging
import re
from typing import Any

from patchright.async_api import Page

from linkedin_mcp_server.tools._common import goto_and_check, parse_count

logger = logging.getLogger(__name__)


def _extract_mutual_connections(text: str) -> int | None:
    match = re.search(r"([\d,.kKmM]+)\s+mutual", text, re.IGNORECASE)
    return parse_count(match.group(1)) if match else None


def _extract_name_headline(text: str) -> tuple[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[0] if lines else "", lines[1] if len(lines) > 1 else "")


async def parse_pending_invitations_page(
    page: Page,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Parse pending incoming invitations from the invitation-manager page.

    Args:
        page: Playwright Page.
        limit: Max invitations to return (default 100).

    Returns:
        List of invitation dicts with name, profile_url, headline,
        and mutual_connections.
    """
    await goto_and_check(page, "https://www.linkedin.com/mynetwork/invitation-manager/")

    safe_limit = max(1, min(limit, 100))
    invitations: list[dict[str, Any]] = []
    rows = page.locator('a[href*="/in/"]')
    total_rows = await rows.count()

    for idx in range(total_rows):
        if len(invitations) >= safe_limit:
            break
        row = rows.nth(idx)
        try:
            text = await row.inner_text(timeout=2000)
            name, headline = _extract_name_headline(text)
            href = await row.get_attribute("href")
            if href and href.startswith("/"):
                href = f"https://www.linkedin.com{href}"
            invitations.append(
                {
                    "name": name,
                    "profile_url": href,
                    "headline": headline,
                    "mutual_connections": _extract_mutual_connections(text),
                }
            )
        except Exception:
            continue

    return invitations
