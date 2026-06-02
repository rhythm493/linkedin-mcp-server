"""Tests for core utility functions (rate-limit detection, scrolling, modals)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_mcp_server.core.exceptions import RateLimitError
from linkedin_mcp_server.core.utils import (
    detect_rate_limit,
    expand_collapsible_sections,
)


@pytest.fixture
def mock_page():
    """Create a mock Patchright page for rate-limit tests."""
    page = MagicMock()
    page.url = "https://www.linkedin.com/in/testuser/details/experience/"

    mock_locator = MagicMock()
    mock_locator.count = AsyncMock(return_value=0)
    mock_locator.inner_text = AsyncMock(return_value="")
    page.locator = MagicMock(return_value=mock_locator)
    return page


class TestDetectRateLimit:
    async def test_checkpoint_url_raises(self, mock_page):
        mock_page.url = "https://www.linkedin.com/checkpoint/challenge/123"
        with pytest.raises(RateLimitError, match="LinkedIn security challenge"):
            await detect_rate_limit(mock_page)

    async def test_authwall_url_raises(self, mock_page):
        mock_page.url = "https://www.linkedin.com/authwall?trk=login"
        with pytest.raises(RateLimitError, match="LinkedIn security challenge"):
            await detect_rate_limit(mock_page)

    async def test_normal_page_with_main_skips_body_heuristic(self, mock_page):
        """A normal page with <main> should NOT trigger body text checks."""
        main_locator = MagicMock()
        main_locator.count = AsyncMock(return_value=1)

        body_locator = MagicMock()
        # Body contains a phrase that would false-positive
        body_locator.inner_text = AsyncMock(
            return_value="Helping SaaS teams slow down churn with data-driven retention"
        )

        def locator_side_effect(selector):
            if selector == "main":
                return main_locator
            if selector == "body":
                return body_locator
            return MagicMock(count=AsyncMock(return_value=0))

        mock_page.locator = MagicMock(side_effect=locator_side_effect)
        # Should NOT raise — the page has <main>, so body heuristic is skipped
        await detect_rate_limit(mock_page)

    async def test_error_page_without_main_triggers_heuristic(self, mock_page):
        """A short error page without <main> with rate-limit text should raise."""
        main_locator = MagicMock()
        main_locator.count = AsyncMock(return_value=0)

        body_locator = MagicMock()
        body_locator.inner_text = AsyncMock(
            return_value="Too many requests. Slow down."
        )

        def locator_side_effect(selector):
            if selector == "main":
                return main_locator
            if selector == "body":
                return body_locator
            return MagicMock(count=AsyncMock(return_value=0))

        mock_page.locator = MagicMock(side_effect=locator_side_effect)
        with pytest.raises(RateLimitError, match="Rate limit message"):
            await detect_rate_limit(mock_page)

    async def test_long_body_without_main_does_not_trigger(self, mock_page):
        """A page without <main> but with long body text (>2000 chars) is not an error page."""
        main_locator = MagicMock()
        main_locator.count = AsyncMock(return_value=0)

        body_locator = MagicMock()
        # Long body with a matching phrase buried in content
        body_locator.inner_text = AsyncMock(
            return_value="x" * 2000 + " try again later"
        )

        def locator_side_effect(selector):
            if selector == "main":
                return main_locator
            if selector == "body":
                return body_locator
            return MagicMock(count=AsyncMock(return_value=0))

        mock_page.locator = MagicMock(side_effect=locator_side_effect)
        # Should NOT raise — body is too long to be an error page
        await detect_rate_limit(mock_page)

    async def test_normal_url_no_error_passes(self, mock_page):
        """A clean normal page passes all checks without raising."""
        main_locator = MagicMock()
        main_locator.count = AsyncMock(return_value=1)

        def locator_side_effect(selector):
            if selector == "main":
                return main_locator
            return MagicMock(count=AsyncMock(return_value=0))

        mock_page.locator = MagicMock(side_effect=locator_side_effect)
        await detect_rate_limit(mock_page)


class TestExpandCollapsibleSections:
    """Tests for the locale-independent collapsible section expansion utility."""

    @pytest.fixture
    def mock_page(self):
        page = MagicMock()

        def make_button(count=0, visible=False):
            btn = MagicMock()
            btn.count = AsyncMock(return_value=count)
            btn.is_visible = AsyncMock(return_value=visible)
            btn.scroll_into_view_if_needed = AsyncMock()
            btn.click = AsyncMock()
            btn.first = btn
            return btn

        page.locator = MagicMock(return_value=make_button(count=0))
        return page

    async def test_clicks_until_button_gone(self, mock_page):
        """Click buttons until count reaches 0."""
        btn = MagicMock()
        btn.count = AsyncMock(side_effect=[1, 1, 0])
        btn.is_visible = AsyncMock(return_value=True)
        btn.scroll_into_view_if_needed = AsyncMock()
        btn.click = AsyncMock()
        btn.first = btn

        mock_page.locator = MagicMock(return_value=btn)

        with patch(
            "linkedin_mcp_server.core.utils.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await expand_collapsible_sections(mock_page)

        assert btn.click.await_count == 2

    async def test_no_button_skips_immediately(self, mock_page):
        """When no button is present, exit immediately."""
        btn = MagicMock()
        btn.count = AsyncMock(return_value=0)
        btn.click = AsyncMock()
        btn.first = btn

        mock_page.locator = MagicMock(return_value=btn)

        with patch(
            "linkedin_mcp_server.core.utils.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await expand_collapsible_sections(mock_page)

        btn.click.assert_not_awaited()

    async def test_invisible_button_skips(self, mock_page):
        """When button exists but is not visible, exit immediately."""
        btn = MagicMock()
        btn.count = AsyncMock(return_value=1)
        btn.is_visible = AsyncMock(return_value=False)
        btn.click = AsyncMock()
        btn.first = btn

        mock_page.locator = MagicMock(return_value=btn)

        with patch(
            "linkedin_mcp_server.core.utils.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await expand_collapsible_sections(mock_page)

        btn.click.assert_not_awaited()

    async def test_respects_max_clicks_budget(self, mock_page):
        """When button never disappears, stop after max_clicks iterations."""
        btn = MagicMock()
        btn.count = AsyncMock(return_value=1)
        btn.is_visible = AsyncMock(return_value=True)
        btn.scroll_into_view_if_needed = AsyncMock()
        btn.click = AsyncMock()
        btn.first = btn

        mock_page.locator = MagicMock(return_value=btn)

        with patch(
            "linkedin_mcp_server.core.utils.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await expand_collapsible_sections(mock_page, max_clicks=3)

        assert btn.click.await_count == 3
