from __future__ import annotations

import re
import logging
from typing import Any

from fastmcp import Context

from linkedin_mcp_server.core.utils import detect_rate_limit
from linkedin_mcp_server.dependencies import get_ready_extractor

logger = logging.getLogger(__name__)

NAVIGATION_RETRIES = 2


async def get_page(ctx: Context | None, tool_name: str) -> Any:
    extractor = await get_ready_extractor(ctx, tool_name=tool_name)
    return extractor.page


async def goto_and_check(page: Any, url: str) -> None:
    last_error: Exception | None = None
    for attempt in range(NAVIGATION_RETRIES + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await detect_rate_limit(page)
            return
        except Exception as exc:
            last_error = exc
            if attempt >= NAVIGATION_RETRIES:
                raise
    if last_error is not None:
        raise last_error


async def ensure_page_healthy(page: Any) -> None:
    await detect_rate_limit(page)


def normalize_profile_url(profile_url: str) -> str:
    normalized = profile_url.strip()
    if not normalized:
        raise ValueError("Invalid LinkedIn profile URL: empty input")
    if "://" not in normalized and normalized.startswith(
        ("/", "linkedin.com/", "www.linkedin.com/")
    ):
        if normalized.startswith("linkedin.com/"):
            normalized = f"https://www.{normalized}"
        elif normalized.startswith("www.linkedin.com/"):
            normalized = f"https://{normalized}"
        else:
            normalized = f"https://www.linkedin.com{normalized if normalized.startswith('/') else '/' + normalized}"
    slug = normalized.strip("/").split("/")[-1]
    return f"https://www.linkedin.com/in/{slug}/"


def parse_count(raw: str) -> int | None:
    if not raw:
        return None
    value = raw.strip().lower().replace(",", "")
    try:
        if value.endswith("k"):
            return int(float(value[:-1]) * 1000)
        if value.endswith("m"):
            return int(float(value[:-1]) * 1_000_000)
        return int(float(value))
    except ValueError:
        digits = re.sub(r"[^0-9]", "", value)
        return int(digits) if digits else None
