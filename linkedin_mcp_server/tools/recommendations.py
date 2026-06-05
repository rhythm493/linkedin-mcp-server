from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.core.pagination import build_paginated_response, decode_cursor
from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.tools._common import get_page
from linkedin_mcp_server.tools._recommendations_scrape import (
    parse_recommendations_page,
)


def register_recommendation_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Get Job Recommendations",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def get_job_recommendations(
        limit: int = 10,
        page: int | None = None,
        next_cursor: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Return LinkedIn's personalized job recommendations feed."""
        safe_limit = max(1, min(limit, 25))
        current_page = decode_cursor(next_cursor, page)
        page_obj = await get_page(ctx, tool_name="get_job_recommendations")

        url = "https://www.linkedin.com/jobs/"
        if current_page > 1:
            url = f"{url}?page={current_page}"

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Loading job recommendations"
            )

        jobs = await parse_recommendations_page(page_obj, limit=safe_limit)

        response = build_paginated_response(
            results=jobs,
            page=current_page,
            limit=safe_limit,
            total=None,
        )
        payload = response.to_dict()
        payload["jobs"] = payload.pop("results")

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Recommendations loaded"
            )

        return payload
