from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.utils import detect_rate_limit_post_action
from linkedin_mcp_server.tools._common import get_page, goto_and_check
from linkedin_mcp_server.tools._pending_invitations_scrape import (
    parse_pending_invitations_page,
)

logger = logging.getLogger(__name__)


def register_network_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Send Connection Request",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def send_connection_request(
        linkedin_username: str,
        ctx: Context | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Send a LinkedIn connection request to a profile."""
        profile_url = f"https://www.linkedin.com/in/{linkedin_username.strip('/')}/"
        page = await get_page(ctx, tool_name="send_connection_request")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Opening profile")

        await goto_and_check(page, profile_url)

        connect_btn = page.get_by_role("button", name="Connect")
        if await connect_btn.count() > 0:
            await connect_btn.first.click()
        else:
            more = page.locator('button[aria-label*="More" i]').first
            if await more.count() > 0:
                await more.click()
                await asyncio.sleep(0.5)
            menu_connect = page.get_by_role("menuitem", name="Connect")
            if await menu_connect.count() == 0:
                menu_connect = page.get_by_text("Connect")
            if await menu_connect.count() > 0:
                await menu_connect.first.click()

        if note:
            add_note = page.get_by_role("button", name="Add a note")
            if await add_note.count() > 0:
                await add_note.click()
                await asyncio.sleep(0.5)
            note_input = page.locator('textarea[name="message"]').first
            if await note_input.count() > 0:
                await note_input.fill(note)

        send = page.locator('button:has-text("Send")').first
        if await send.count() > 0:
            await send.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Connection request sent"
            )

        return {
            "message": "Connection request sent successfully.",
            "resource_url": profile_url,
        }

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Pending Invitations",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def get_pending_invitations(
        limit: int = 20,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """List pending incoming LinkedIn invitations."""
        page = await get_page(ctx, tool_name="get_pending_invitations")

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Loading invitation manager"
            )

        invitations = await parse_pending_invitations_page(page, limit=limit)

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Invitations loaded"
            )

        return {"invitations": invitations}

    @mcp.tool(
        timeout=tool_timeout,
        title="Follow Person",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def follow_person(
        linkedin_username: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Follow a LinkedIn person profile."""
        profile_url = f"https://www.linkedin.com/in/{linkedin_username.strip('/')}/"
        page = await get_page(ctx, tool_name="follow_person")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Opening profile")

        await goto_and_check(page, profile_url)

        follow_btn = page.get_by_role("button", name="Follow")
        if await follow_btn.count() > 0:
            await follow_btn.first.click()
        else:
            more = page.locator('button[aria-label*="More" i]').first
            if await more.count() > 0:
                await more.click()
                await asyncio.sleep(0.5)
            menu_follow = page.get_by_role("menuitem", name="Follow")
            if await menu_follow.count() == 0:
                menu_follow = page.get_by_text("Follow")
            if await menu_follow.count() > 0:
                await menu_follow.first.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Profile followed"
            )

        return {
            "message": "Followed profile successfully.",
            "resource_url": profile_url,
        }
