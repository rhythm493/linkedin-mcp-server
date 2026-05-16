from __future__ import annotations

import logging
import re
from typing import Any
from dataclasses import dataclass

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.pagination import build_paginated_response, decode_cursor
from linkedin_mcp_server.tools._common import get_page, goto_and_check

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


def register_people_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Get Company People",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def get_company_people(
        company_name: str,
        ctx: Context | None = None,
        title_keyword: str | None = None,
        limit: int = 10,
        page: int | None = None,
        next_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get people at a company with optional title filter."""
        safe_limit = max(1, min(limit, 25))
        current_page = decode_cursor(next_cursor, page)
        page_obj = await get_page(ctx, tool_name="get_company_people")

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Loading company people page"
            )

        slug = company_name.strip().lower().replace(" ", "-")
        url = f"https://www.linkedin.com/company/{slug}/people/"
        await goto_and_check(page_obj, url)

        try:
            await page_obj.wait_for_selector("main", timeout=5000)
        except Exception:
            pass

        rows = page_obj.locator('a[href*="/in/"], li:has(a[href*="/in/"])')
        total_rows = await rows.count()
        people: list[dict[str, Any]] = []

        for idx in range(total_rows):
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
            if len(people) >= safe_limit:
                break

        total_results = None
        try:
            body_text = await page_obj.locator("body").inner_text(timeout=1000)
            total_results = _extract_total_count(body_text)
        except Exception:
            pass

        response = build_paginated_response(
            results=people,
            page=current_page,
            limit=safe_limit,
            total=total_results,
        )
        payload = response.to_dict()

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Company people search complete"
            )

        return payload
