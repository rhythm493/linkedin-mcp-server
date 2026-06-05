from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.pagination import build_paginated_response, decode_cursor
from linkedin_mcp_server.core.utils import detect_rate_limit_post_action
from linkedin_mcp_server.tools._common import get_page, goto_and_check
from linkedin_mcp_server.tools._saved_jobs_scrape import (
    _extract_job_id,
    parse_saved_jobs_page,
)

logger = logging.getLogger(__name__)


def register_saved_job_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Save Job",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def save_job(
        job_url: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Save a LinkedIn job posting for later review."""
        normalized = job_url.strip()
        if not normalized.startswith("http"):
            if normalized.startswith("/"):
                normalized = f"https://www.linkedin.com{normalized}"
            else:
                normalized = f"https://www.linkedin.com/jobs/view/{normalized}"
        normalized = normalized.rstrip("/")

        page = await get_page(ctx, tool_name="save_job")

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Opening job posting"
            )

        await goto_and_check(page, normalized)
        already_saved = False
        try:
            saved_button = page.locator('button[aria-label*="Remove from"]')
            already_saved = await saved_button.count() > 0
        except Exception:
            pass

        if not already_saved:
            save_button = page.locator(
                'button[aria-label*="Save"], button[aria-label*="save"]'
            ).first
            if await save_button.count() > 0:
                await save_button.click()
                await asyncio.sleep(1)
            await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Job saved")

        return {
            "status": "saved",
            "message": "Job already saved."
            if already_saved
            else "Job saved successfully.",
            "job_url": normalized,
            "job_id": _extract_job_id(normalized),
        }

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Saved Jobs",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def get_saved_jobs(
        limit: int = 10,
        page: int | None = None,
        next_cursor: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Return the current user's saved jobs list."""
        safe_limit = max(1, min(limit, 25))
        current_page = decode_cursor(next_cursor, page)
        page_obj = await get_page(ctx, tool_name="get_saved_jobs")

        # cardType=SAVED selects the Saved tab; start=offset handles pagination
        start = (current_page - 1) * 10
        url = f"https://www.linkedin.com/my-items/saved-jobs/?cardType=SAVED&start={start}"

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Loading saved jobs"
            )

        jobs, _ = await parse_saved_jobs_page(page_obj, url, limit=safe_limit)

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
                progress=100, total=100, message="Saved jobs loaded"
            )

        return payload
