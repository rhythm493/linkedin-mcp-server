from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import Context, FastMCP

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.utils import detect_rate_limit_post_action
from linkedin_mcp_server.tools._common import get_page, goto_and_check

logger = logging.getLogger(__name__)


def register_profile_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    @mcp.tool(
        timeout=tool_timeout,
        title="Update Profile Headline",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def update_profile_headline(
        headline: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Update the logged-in user's LinkedIn headline."""
        if not headline.strip():
            raise ValueError("headline must not be empty")

        page = await get_page(ctx, tool_name="update_profile_headline")

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Opening profile editor"
            )

        await goto_and_check(page, "https://www.linkedin.com/in/me/")

        edit_btn = page.locator(
            'a[aria-label*="Edit" i][href*="edit" i], a[href*="/edit/intro/"]'
        ).first
        if await edit_btn.count() > 0:
            await edit_btn.click()
            await asyncio.sleep(2)

        headline_input = page.locator(
            'input[name="headline"], input[placeholder*="Headline"]'
        ).first
        if await headline_input.count() > 0:
            await headline_input.fill("")
            await headline_input.fill(headline)
        else:
            raise ValueError("Could not find headline input field")

        save = page.locator('button:has-text("Save")').first
        if await save.count() > 0:
            await save.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Headline updated"
            )

        return {
            "message": "Profile headline updated successfully.",
            "new_headline": headline,
        }

    @mcp.tool(
        timeout=tool_timeout,
        title="Set Open To Work",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def set_open_to_work(
        enabled: bool,
        visibility: str = "all_members",
        job_titles: list[str] | None = None,
        locations: list[str] | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Enable or disable the Open To Work profile signal."""
        page = await get_page(ctx, tool_name="set_open_to_work")

        if ctx:
            await ctx.report_progress(progress=0, total=100, message="Opening profile")

        await goto_and_check(page, "https://www.linkedin.com/in/me/")

        otw_btn = page.locator(
            'button:has-text("Open to"), button[aria-label*="Open to"]'
        ).first
        if await otw_btn.count() > 0:
            await otw_btn.click()
            await asyncio.sleep(2)

        if enabled:
            if job_titles:
                title_input = page.locator(
                    'input[placeholder*="title"], input[name="jobTitle"]'
                ).first
                if await title_input.count() > 0:
                    await title_input.fill(job_titles[0])
            if locations:
                loc_input = page.locator(
                    'input[placeholder*="location"], input[name="location"]'
                ).first
                if await loc_input.count() > 0:
                    await loc_input.fill(locations[0])
            if visibility.strip().lower() == "recruiters_only":
                recruiters = page.locator('label:has-text("Recruiters only")').first
                if await recruiters.count() > 0:
                    await recruiters.click()
            else:
                public = page.locator('label:has-text("All members")').first
                if await public.count() > 0:
                    await public.click()
        else:
            remove = page.locator('button:has-text("Remove")').first
            if await remove.count() > 0:
                await remove.click()

        save = page.locator('button:has-text("Save")').first
        if await save.count() > 0:
            await save.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(
                progress=100, total=100, message="Open To Work updated"
            )

        return {
            "message": "Open To Work settings updated successfully.",
            "enabled": enabled,
            "visibility": visibility,
        }

    @mcp.tool(
        timeout=tool_timeout,
        title="Add Profile Skills",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        },
    )
    async def add_profile_skills(
        skills: list[str],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Add new skills to the logged-in user's profile."""
        requested = [s.strip() for s in skills if s.strip()]
        if not requested:
            raise ValueError("skills must contain at least one non-empty value")

        page = await get_page(ctx, tool_name="add_profile_skills")

        if ctx:
            await ctx.report_progress(
                progress=0, total=100, message="Opening skills editor"
            )

        await goto_and_check(page, "https://www.linkedin.com/in/me/details/skills/")

        for skill in requested:
            add_btn = page.locator(
                'button:has-text("Add"), button[aria-label*="Add skill"]'
            ).first
            if await add_btn.count() > 0:
                await add_btn.click()
                await asyncio.sleep(0.5)
            else:
                section = page.locator('section:has-text("Skills")').first
                add_link = section.locator(
                    'a:has-text("Add"), button:has-text("Add")'
                ).first
                if await add_link.count() > 0:
                    await add_link.click()
                    await asyncio.sleep(0.5)

            skill_input = page.locator(
                'input[placeholder*="skill"], input[aria-label*="Skill"]'
            ).first
            if await skill_input.count() > 0:
                await skill_input.fill(skill)
                await asyncio.sleep(0.5)

        save = page.locator('button:has-text("Save")').first
        if await save.count() > 0:
            await save.click()

        await detect_rate_limit_post_action(page)

        if ctx:
            await ctx.report_progress(progress=100, total=100, message="Skills added")

        return {
            "message": "Profile skills updated successfully.",
            "added_skills": requested,
        }
