from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.pagination import build_paginated_response, decode_cursor
from linkedin_mcp_server.core.utils import detect_rate_limit_post_action
from linkedin_mcp_server.tools._common import get_page, goto_and_check

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
    company = lines[1]
    location = lines[2] if len(lines) > 2 else None
    posting_date = None
    for line in lines[2:]:
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

        url = "https://www.linkedin.com/my-items/saved-jobs/"
        if current_page > 1:
            url = f"{url}?page={current_page}"

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Loading saved jobs"
            )

        await goto_and_check(page_obj, url)
        await asyncio.sleep(2)

        rows = page_obj.locator("li, article, .job-card-container, [data-job-id]")
        jobs: list[dict[str, Any]] = []
        total_rows = await rows.count()

        for idx in range(total_rows):
            row = rows.nth(idx)
            anchor = row.locator("a[href*='/jobs/view/']").first
            href = (
                await anchor.get_attribute("href") if await anchor.count() > 0 else None
            )
            if href and href.startswith("/"):
                href = f"https://www.linkedin.com{href}"
            try:
                text = await row.inner_text(timeout=1000)
            except Exception:
                continue
            card = _parse_saved_job_card_text(text, job_url=href)
            if card is None:
                continue
            jobs.append(card)
            if len(jobs) >= safe_limit:
                break

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
