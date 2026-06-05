"""Standalone company-people page scraping on a given Playwright page."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from patchright.async_api import Page

from linkedin_mcp_server.tools._common import goto_and_check

logger = logging.getLogger(__name__)

_CONNECTION_DEGREE_RE = re.compile(r"\b(1st|2nd|3rd)\b", re.IGNORECASE)
_SHARED_CONNECTIONS_RE = re.compile(r"(\d+)\s+shared connections?", re.IGNORECASE)
_RESULT_COUNT_RE = re.compile(r"([\d,]+)\+?\s+results", re.IGNORECASE)


@dataclass
class PersonCard:
    name: str
    profile_url: str | None
    headline: str | None = None
    location: str | None = None
    connection_degree: str | None = None
    shared_connections: int | None = None
    current_company: str | None = None
    past_companies: list[str] | None = None


def _normalize_profile_url(href: str | None) -> str | None:
    if not href:
        return None
    candidate = href.strip()
    if not candidate:
        return None
    if candidate.startswith("/"):
        candidate = f"https://www.linkedin.com{candidate}"
    if "linkedin.com/in/" not in candidate:
        return None
    return candidate


def _extract_connection_degree(text: str) -> str | None:
    match = _CONNECTION_DEGREE_RE.search(text)
    return match.group(1) if match else None


def _extract_shared_connections(text: str) -> int | None:
    match = _SHARED_CONNECTIONS_RE.search(text)
    return int(match.group(1)) if match else None


def _extract_total_count(text: str) -> int | None:
    match = _RESULT_COUNT_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_person_card_text(text: str, *, profile_url: str | None) -> PersonCard | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not profile_url:
        return None
    name = re.sub(
        r"\s*[•·]\s*(1st|2nd|3rd\+?)\s*$", "", lines[0], flags=re.IGNORECASE
    ).strip()
    headline = None
    location = None
    connection_degree = None
    shared_connections = None
    remaining = lines[1:]
    if remaining and not _CONNECTION_DEGREE_RE.search(remaining[0]):
        headline = remaining[0]
        remaining = remaining[1:]
    for line in remaining:
        if shared_connections is None:
            shared_connections = _extract_shared_connections(line)
            if shared_connections is not None:
                continue
        if connection_degree is None:
            connection_degree = _extract_connection_degree(line)
            if connection_degree is not None:
                continue
        if location is None and ("," in line or "remote" in line.lower()):
            location = line
    return PersonCard(
        name=name,
        profile_url=profile_url,
        headline=headline,
        location=location,
        connection_degree=connection_degree,
        shared_connections=shared_connections,
    )


async def parse_company_people_page(
    page: Page,
    company_name: str,
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Parse people listing from a company's /people/ page.

    Args:
        page: Playwright Page.
        company_name: LinkedIn company slug (e.g. "docker").
        limit: Max people to return (default 25, max 25).

    Returns:
        List of person dicts with name, profile_url, headline, location,
        connection_degree, and shared_connections.
    """
    slug = company_name.strip().lower().replace(" ", "-")
    url = f"https://www.linkedin.com/company/{slug}/people/"
    await goto_and_check(page, url)

    try:
        await page.wait_for_selector("main", timeout=5000)
    except Exception:
        pass

    rows = page.locator('a[href*="/in/"], li:has(a[href*="/in/"])')
    total_rows = await rows.count()
    safe_limit = max(1, min(limit, 25))
    people: list[dict[str, Any]] = []

    for idx in range(total_rows):
        if len(people) >= safe_limit:
            break
        row = rows.nth(idx)
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
        if card is None:
            continue
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

    return people


async def extract_total_text_count(page: Page) -> int | None:
    """Extract total people count from the page body text."""
    try:
        body_text = await page.locator("body").inner_text(timeout=1000)
        return _extract_total_count(body_text)
    except Exception:
        return None
