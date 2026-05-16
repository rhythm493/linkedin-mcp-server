from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.utils import detect_rate_limit_post_action
from linkedin_mcp_server.tools._common import get_page, goto_and_check

logger = logging.getLogger(__name__)

ALLOWED_REACTIONS = {
    "like": "Like",
    "celebrate": "Celebrate",
    "support": "Support",
    "funny": "Funny",
    "love": "Love",
    "insightful": "Insightful",
}


def register_engagement_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="React To Post",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def react_to_post(
        post_url: str,
        reaction: str = "like",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """React to a LinkedIn post with a specific reaction."""
        normalized = reaction.strip().lower()
        if normalized not in ALLOWED_REACTIONS:
            raise ValueError(
                f"Unsupported reaction '{reaction}'. Allowed: {', '.join(sorted(ALLOWED_REACTIONS))}"
            )

        page = await get_page(ctx, tool_name="react_to_post")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Loading post")

        await goto_and_check(page, post_url)

        like_button = page.locator(
            'button[aria-label*="Like"], button:has-text("Like")'
        ).first
        if await like_button.count() > 0:
            await like_button.hover()
            await asyncio.sleep(0.5)

            reaction_name = ALLOWED_REACTIONS[normalized]
            picker = page.locator(
                f'button[aria-label="{reaction_name}"], button:has-text("{reaction_name}")'
            ).first
            if await picker.count() > 0:
                await picker.click()
            else:
                await like_button.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Reaction added")

        return {
            "message": f"Applied '{normalized}' reaction.",
            "resource_url": post_url,
        }

    @mcp.tool(
        timeout=tool_timeout,
        title="Comment On Post",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def comment_on_post(
        post_url: str,
        text: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Add a comment to a LinkedIn post."""
        page = await get_page(ctx, tool_name="comment_on_post")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Loading post")

        await goto_and_check(page, post_url)

        comment_input = page.locator(
            'div[role="textbox"][aria-label*="comment" i], div[aria-label*="Write a comment" i]'
        ).first
        if await comment_input.count() > 0:
            await comment_input.click()
            await comment_input.fill(text)
            await asyncio.sleep(0.5)
        else:
            raise ValueError("Could not find comment input")

        post_btn = page.locator('button:has-text("Post")').first
        if await post_btn.count() > 0:
            await post_btn.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Comment posted")

        return {"message": "Comment posted.", "resource_url": post_url}

    @mcp.tool(
        timeout=tool_timeout,
        title="Like Comment",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def like_comment(
        post_url: str,
        comment_index: int = 0,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Like the Nth comment on a LinkedIn post."""
        if comment_index < 0:
            raise ValueError("comment_index must be >= 0")

        page = await get_page(ctx, tool_name="like_comment")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Loading comments")

        await goto_and_check(page, post_url)

        comment = page.locator(
            "article.comments-comment-item, li.comments-comment-item"
        ).nth(comment_index)
        like_button = comment.locator('button:has-text("Like")').first
        if await like_button.count() > 0:
            await like_button.click()
        else:
            raise ValueError(f"Like button not found for comment index {comment_index}")

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Comment liked")

        return {
            "message": f"Liked comment index {comment_index}.",
            "resource_url": post_url,
        }
