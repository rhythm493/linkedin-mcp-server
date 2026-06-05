from __future__ import annotations

import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.pagination import build_paginated_response, decode_cursor
from linkedin_mcp_server.tools._common import get_page
from linkedin_mcp_server.tools._company_people_scrape import (
    _extract_total_count,
    parse_company_people_page,
)

logger = logging.getLogger(__name__)


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

        people = await parse_company_people_page(
            page_obj, company_name, limit=safe_limit
        )

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
