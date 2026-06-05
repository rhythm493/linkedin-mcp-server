"""Standalone job-recommendations page scraping on a given Playwright page."""

from __future__ import annotations

import re
from typing import Any

from patchright.async_api import Page

from linkedin_mcp_server.tools._common import goto_and_check

_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")
_TITLE_SELECTORS = (
    ".job-card-list__title",
    ".job-card-container__link",
    "a[href*='/jobs/view/']",
)
_COMPANY_SELECTORS = (
    ".artdeco-entity-lockup__subtitle",
    ".job-card-container__company-name",
)
_LOCATION_SELECTORS = (
    ".job-card-container__metadata-item",
    ".job-card-container__metadata-wrapper",
)
_LINK_SELECTORS = ("a[href*='/jobs/view/']",)
_NOISE = {
    "top job picks for you",
    "based on your profile, preferences, and activity like applies, searches, and saves",
    "promoted",
    "easy apply",
    "show all",
    "load more",
    "top job picks",
}
_LOCATION_HINT_RE = re.compile(
    r"(remote|hybrid|on-site|onsite|india|singapore|delhi|gurugram|bangalore|mumbai|new york|london|\()",
    re.IGNORECASE,
)
_VERIFIED_JOB_RE = re.compile(r"\s+\(verified job\)\s*$", re.IGNORECASE)
_ANCILLARY_LINE_RE = re.compile(
    r"(actively reviewing applicants|company alumni works here|promoted|easy apply|applied|resume matched)",
    re.IGNORECASE,
)


def _extract_job_id(job_url: str | None) -> str | None:
    if not job_url:
        return None
    match = _JOB_ID_RE.search(job_url)
    return match.group(1) if match else None


def _normalize_job_url(href: str | None) -> str | None:
    if not href:
        return None
    candidate = href.strip()
    if candidate.startswith("/"):
        candidate = f"https://www.linkedin.com{candidate}"
    return candidate.rstrip("/") if candidate.startswith("http") else None


def _build_job_result(
    title: str | None,
    company: str | None,
    location: str | None,
    job_id: str | None,
    job_url: str | None,
) -> dict[str, str | None] | None:
    if not title or not company:
        return None
    return {
        "title": title,
        "company": company,
        "location": location,
        "job_id": job_id,
        "job_url": job_url,
    }


def _first_locator_text(row: Any, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        loc = row.locator(sel).first
        try:
            if loc.count() > 0:
                text = loc.inner_text(timeout=500)
                if text:
                    return " ".join(text.split())
        except Exception:
            continue
    return None


def _first_locator_href(row: Any, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        loc = row.locator(sel).first
        try:
            if loc.count() > 0:
                href = loc.get_attribute("href", timeout=500)
                if href:
                    return href
        except Exception:
            continue
    return None


def _clean_line(line: str) -> str:
    line = " ".join(line.split()).strip()
    return "" if not line or line in {"•", "·"} else line


def _parse_recommendations_text(
    text: str, limit: int = 10
) -> list[dict[str, str | None]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    try:
        start = next(
            idx
            for idx, line in enumerate(lines)
            if line.lower().startswith("top job picks")
            or line.lower().startswith("recommended for you")
        )
        lines = lines[start + 1 :]
    except StopIteration:
        pass

    filtered: list[str] = []
    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line or line.lower() in _NOISE:
            continue
        filtered.append(line)

    jobs: list[dict[str, str | None]] = []
    seen: set[str] = set()
    idx = 0
    while idx < len(filtered) and len(jobs) < limit:
        while idx < len(filtered) and (
            filtered[idx].lower() in _NOISE or _ANCILLARY_LINE_RE.search(filtered[idx])
        ):
            idx += 1
        if idx >= len(filtered):
            break
        title = filtered[idx]
        if len(title) < 3:
            idx += 1
            continue
        title = _VERIFIED_JOB_RE.sub("", title).strip()
        next_idx = idx + 1
        while next_idx < len(filtered) and _ANCILLARY_LINE_RE.search(
            filtered[next_idx]
        ):
            next_idx += 1
        if next_idx >= len(filtered):
            break
        company = filtered[next_idx]
        next_idx += 1
        location = None
        while next_idx < len(filtered):
            candidate = filtered[next_idx]
            if _LOCATION_HINT_RE.search(candidate):
                location = candidate
                next_idx += 1
                break
            if candidate.lower() in _NOISE or _ANCILLARY_LINE_RE.search(candidate):
                next_idx += 1
                continue
            break
        job = _build_job_result(
            title=title,
            company=company,
            location=location,
            job_id=None,
            job_url=None,
        )
        idx = next_idx if next_idx > idx else idx + 1
        if job is None:
            continue
        dedupe_key = f"{job['title']}::{job['company']}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        jobs.append(job)
    return jobs


async def parse_recommendations_page(
    page: Page,
    *,
    limit: int = 10,
) -> list[dict[str, str | None]]:
    """Parse job recommendations from the LinkedIn jobs homepage.

    Tries structured DOM selectors first, falls back to body text parsing.
    """
    await goto_and_check(page, "https://www.linkedin.com/jobs/")

    jobs: list[dict[str, str | None]] = []
    try:
        rows = page.locator(
            ".job-card-container, [data-job-id], article.job-card-list__container"
        )
        for idx in range(await rows.count()):
            if len(jobs) >= limit:
                break
            row = rows.nth(idx)
            title = _first_locator_text(row, _TITLE_SELECTORS)
            company = _first_locator_text(row, _COMPANY_SELECTORS)
            location = _first_locator_text(row, _LOCATION_SELECTORS)
            href = _first_locator_href(row, _LINK_SELECTORS)
            job_url = _normalize_job_url(href)
            job = _build_job_result(
                title=title,
                company=company,
                location=location,
                job_id=_extract_job_id(job_url),
                job_url=job_url,
            )
            if job is not None:
                jobs.append(job)
    except Exception:
        pass

    if not jobs:
        try:
            body_text = await page.locator("body").inner_text(timeout=2000)
            jobs = _parse_recommendations_text(body_text, limit=limit)
        except Exception:
            pass

    return jobs
