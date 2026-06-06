"""Tests for standalone job scraping on a given page."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.tools import _job_scrape
from linkedin_mcp_server.tools._job_scrape import scrape_job_on_page


def _make_mock_page(
    *,
    text: str = "",
    has_main: bool = True,
    goto_fail: bool = False,
) -> MagicMock:
    page = MagicMock()
    if goto_fail:
        from patchright.async_api import TimeoutError as PwTimeout

        page.goto = AsyncMock(side_effect=PwTimeout("Navigation timeout"))
    else:
        page.goto = AsyncMock()

    page.url = "https://www.linkedin.com/"
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.evaluate = AsyncMock(return_value=0)

    # Universal locator that returns a mock with all async methods
    def _make_loc(
        count: int = 0, inner_text: str = "", is_visible: bool = False
    ) -> MagicMock:
        loc = MagicMock()
        loc.count = AsyncMock(return_value=count)
        loc.inner_text = AsyncMock(return_value=inner_text)
        loc.is_visible = AsyncMock(return_value=is_visible)
        loc.first = loc
        loc.nth = MagicMock(side_effect=lambda _: loc)
        loc.click = AsyncMock()
        loc.locator = MagicMock(side_effect=lambda selector: _make_loc())
        return loc

    main_loc = _make_loc(count=1 if has_main else 0, inner_text=text)
    page.locator = MagicMock(
        side_effect=lambda selector: main_loc if selector == "main" else _make_loc()
    )
    return page


@pytest.mark.asyncio
async def test_scrape_job_success():
    page = _make_mock_page(text="Senior Engineer at Google\nSan Francisco")
    result = await scrape_job_on_page(page, "123456")
    assert result["url"] == "https://www.linkedin.com/jobs/view/123456/"
    assert (
        result["sections"]["job_posting"] == "Senior Engineer at Google\nSan Francisco"
    )
    assert "section_errors" not in result


@pytest.mark.asyncio
async def test_scrape_job_navigation_timeout():
    page = _make_mock_page(goto_fail=True)
    result = await scrape_job_on_page(page, "123456")
    assert result["sections"] == {}
    assert "section_errors" in result
    assert "error" in result["section_errors"]["job_posting"]


@pytest.mark.asyncio
async def test_scrape_job_empty_content():
    page = _make_mock_page(text="")
    result = await scrape_job_on_page(page, "123456")
    assert result["sections"] == {}
    assert "section_errors" not in result


@pytest.mark.asyncio
async def test_scrape_job_rate_limited():
    page = _make_mock_page(text="Rate limited content")
    result = await scrape_job_on_page(page, "123456")
    assert "url" in result


@pytest.mark.asyncio
async def test_scrape_job_exception_during_extraction():
    page = MagicMock()
    page.goto = AsyncMock(side_effect=RuntimeError("Crash"))
    result = await scrape_job_on_page(page, "123456")
    assert result["sections"] == {}
    assert "error" in result["section_errors"]["job_posting"]


@pytest.mark.asyncio
async def test_scrape_job_expands_collapsible_sections():
    """Parallel path calls expand_collapsible_sections before extraction."""
    page = _make_mock_page(text="Senior Engineer at Google\nSan Francisco")
    with patch(
        "linkedin_mcp_server.tools._job_scrape.expand_collapsible_sections",
        new_callable=AsyncMock,
    ) as mock_expand:
        result = await scrape_job_on_page(page, "123456")

    mock_expand.assert_awaited_once()
    assert "job_posting" in result["sections"]


@pytest.mark.asyncio
async def test_scrape_job_auth_barrier_raises():
    page = MagicMock()
    page.goto = AsyncMock()
    page.url = "https://www.linkedin.com/login/"
    page.title = AsyncMock(return_value="Sign in to LinkedIn")
    with pytest.raises(AuthenticationError):
        await scrape_job_on_page(page, "123456")


@pytest.mark.asyncio
async def test_scrape_job_retries_on_rate_limit():
    page = _make_mock_page(text="Senior Engineer at Google")
    rate_limited = _job_scrape.ExtractedSection(
        text=_job_scrape._RATE_LIMITED_MSG, references=[]
    )
    content = _job_scrape.ExtractedSection(
        text="Senior Engineer at Google", references=[]
    )
    with patch.object(
        _job_scrape, "_extract_job_page", side_effect=[rate_limited, content]
    ):
        result = await scrape_job_on_page(page, "123456")
    assert result["sections"]["job_posting"] == "Senior Engineer at Google"


@pytest.mark.asyncio
async def test_scrape_job_retry_still_fails_on_second_attempt():
    page = _make_mock_page(text="noise")
    rate_limited = _job_scrape.ExtractedSection(
        text=_job_scrape._RATE_LIMITED_MSG, references=[]
    )
    with patch.object(_job_scrape, "_extract_job_page", return_value=rate_limited):
        result = await scrape_job_on_page(page, "123456")
    assert result["sections"] == {}


@pytest.mark.asyncio
async def test_scrape_job_no_auth_check_when_disabled():
    page = _make_mock_page(text="")
    result = await scrape_job_on_page(page, "123456", check_auth=False)
    assert result["sections"] == {}
    assert "section_errors" not in result
