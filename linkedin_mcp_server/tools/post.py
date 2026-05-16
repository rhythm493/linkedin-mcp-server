from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.utils import detect_rate_limit_post_action
from linkedin_mcp_server.tools._common import get_page, goto_and_check

logger = logging.getLogger(__name__)


def register_post_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Create Post",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def create_post(
        text: str,
        ctx: Context | None = None,
        visibility: str = "anyone",
    ) -> dict[str, Any]:
        """Create a LinkedIn post from the feed composer."""
        page = await get_page(ctx, tool_name="create_post")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Opening composer")

        await goto_and_check(page, "https://www.linkedin.com/feed/")
        await asyncio.sleep(3)

        trigger = page.locator(
            'div[role="button"]:has-text("Start a post"), div[role="button"]:has-text("Share"), div.share-box-feed-entry__trigger'
        ).first
        if await trigger.count() > 0:
            await trigger.click()
            await asyncio.sleep(2)

        editor = page.locator(
            ".ql-editor[contenteditable='true'], div[role='textbox']"
        ).first
        if await editor.count() > 0:
            await editor.click()
            await asyncio.sleep(0.5)
            await editor.fill(text)
        else:
            raise ValueError("Could not find post composer editor")

        await asyncio.sleep(1)

        submit = page.locator('button:has-text("Post")').first
        if await submit.count() > 0:
            await submit.click()
        else:
            raise ValueError("Could not find submit button")

        await detect_rate_limit_post_action(page)
        await asyncio.sleep(2)

        post_url = None
        try:
            post_link = page.locator('a[href*="/feed/update/"]').first
            if await post_link.count() > 0:
                href = await post_link.get_attribute("href")
                if href:
                    post_url = (
                        f"https://www.linkedin.com{href}"
                        if href.startswith("/")
                        else href
                    )
        except Exception:
            pass

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Post created")

        return {"message": "Post created successfully.", "resource_url": post_url}

    @mcp.tool(
        timeout=tool_timeout,
        title="Create Poll",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def create_poll(
        question: str,
        options: list[str],
        ctx: Context | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Create a LinkedIn poll post with 2-4 options."""
        if len(options) < 2 or len(options) > 4:
            raise ValueError("Poll options must contain between 2 and 4 entries")

        page = await get_page(ctx, tool_name="create_poll")

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Opening poll composer"
            )

        await goto_and_check(page, "https://www.linkedin.com/feed/")
        await asyncio.sleep(3)

        trigger = page.locator(
            'div[role="button"]:has-text("Start a post"), div[role="button"]:has-text("Share"), div.share-box-feed-entry__trigger'
        ).first
        if await trigger.count() > 0:
            await trigger.click()
            await asyncio.sleep(2)

        poll_button = page.locator(
            'button:has-text("Poll"), button[aria-label*="Poll"]'
        ).first
        if await poll_button.count() > 0:
            await poll_button.click()
            await asyncio.sleep(1)

        if text:
            editor = page.locator(".ql-editor[contenteditable='true']").first
            if await editor.count() > 0:
                await editor.click()
                await editor.fill(text)

        question_input = page.locator(
            "input[name='question'], input[placeholder*='Question']"
        ).first
        if await question_input.count() > 0:
            await question_input.fill(question)

        for idx, option in enumerate(options[:4]):
            option_input = page.locator(
                f"input[name='option{idx + 1}'], input[placeholder*='Option {idx + 1}']"
            ).first
            if await option_input.count() > 0:
                await option_input.fill(option)

        submit = page.locator('button:has-text("Post")').first
        if await submit.count() > 0:
            await submit.click()

        await detect_rate_limit_post_action(page)
        await asyncio.sleep(2)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Poll created")

        return {"message": "Poll created successfully."}

    @mcp.tool(
        timeout=tool_timeout,
        title="Delete Post",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
    )
    async def delete_post(
        post_url: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Delete a LinkedIn post by URL."""
        page = await get_page(ctx, tool_name="delete_post")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Loading post")

        await goto_and_check(page, post_url)

        menu = page.locator(
            'button[aria-label*="More"], button[aria-label*="more"]'
        ).first
        if await menu.count() > 0:
            await menu.click()
            await asyncio.sleep(0.5)

        delete = page.locator(
            'div[role="button"]:has-text("Delete post"), div[role="menuitem"]:has-text("Delete")'
        ).first
        if await delete.count() > 0:
            await delete.click()
            await asyncio.sleep(0.5)

        confirm = page.locator('button:has-text("Delete")').last
        if await confirm.count() > 0:
            await confirm.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Post deleted")

        return {"message": "Post deleted successfully.", "resource_url": post_url}

    @mcp.tool(
        timeout=tool_timeout,
        title="Repost",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def repost(
        post_url: str,
        ctx: Context | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Repost an existing LinkedIn post with optional commentary."""
        page = await get_page(ctx, tool_name="repost")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Loading post")

        await goto_and_check(page, post_url)

        repost_btn = page.locator(
            'button[aria-label*="Repost"], button:has-text("Repost")'
        ).first
        if await repost_btn.count() > 0:
            await repost_btn.click()
            await asyncio.sleep(1)

        if comment:
            thoughts = page.locator(
                'div[role="menuitem"]:has-text("with thoughts"), div[aria-label*="thoughts"]'
            ).first
            if await thoughts.count() > 0:
                await thoughts.click()
                await asyncio.sleep(1)
            editor = page.locator(".ql-editor[contenteditable='true']").first
            if await editor.count() > 0:
                await editor.fill(comment)
            submit = page.locator('button:has-text("Post")').first
            if await submit.count() > 0:
                await submit.click()
        else:
            now_btn = page.locator(
                'div[role="menuitem"]:has-text("Repost now"), div[aria-label*="Repost now"]'
            ).first
            if await now_btn.count() > 0:
                await now_btn.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Repost complete"
            )

        return {"message": "Repost submitted successfully.", "resource_url": post_url}
