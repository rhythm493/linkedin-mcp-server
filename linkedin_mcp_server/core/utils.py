"""Utility functions for scraping operations."""

import asyncio
import logging
import random

from patchright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .exceptions import RateLimitError

logger = logging.getLogger(__name__)

_WAIT_FOR_CHALLENGE_RESOLVE = 120  # seconds to wait for manual CAPTCHA solve


async def _has_visible_captcha(page: Page) -> bool:
    """Check if any visible CAPTCHA iframe is present on the page.

    LinkedIn embeds Google reCAPTCHA Enterprise in invisible mode on
    every page for bot detection.  That iframe is always present but
    never visible.  A real challenge shows a visible CAPTCHA iframe
    instead — that is what we need to detect.
    """
    locator = page.locator('iframe[src*="captcha"]')
    count = await locator.count()
    for i in range(count):
        try:
            if await locator.nth(i).is_visible():
                return True
        except PlaywrightTimeoutError:
            continue
    return False


async def _wait_for_challenge_resolve(page: Page) -> None:
    """Wait for the user to manually resolve a security challenge.

    Polls the page URL and CAPTCHA iframes until the challenge is gone.
    Used only when the browser is in non-headless mode so the user can
    interact with the challenge page.
    """
    logger.warning(
        "Security challenge detected. "
        "Solve it in the browser window — waiting up to %d seconds.",
        _WAIT_FOR_CHALLENGE_RESOLVE,
    )
    for _ in range(_WAIT_FOR_CHALLENGE_RESOLVE):
        await asyncio.sleep(1)
        current_url = page.url
        if any(
            trigger in current_url
            for trigger in ("/checkpoint", "/authwall", "/captcha")
        ):
            continue
        if await _has_visible_captcha(page):
            continue
        logger.info("Security challenge resolved by user.")
        return
    logger.warning("Security challenge wait timed out after %d seconds.", _WAIT_FOR_CHALLENGE_RESOLVE)


def _is_headless() -> bool:
    """Check whether the browser is in headless mode.

    Returns ``True`` by default.  Delegates to ``drivers.browser._headless``
    if it can be imported without cycling.
    """
    try:
        from linkedin_mcp_server.drivers.browser import _headless as _hl

        return _hl
    except (ImportError, AttributeError):
        return True


async def detect_rate_limit(page: Page, headless: bool | None = None) -> None:
    """Detect if LinkedIn has rate-limited or security-challenged the session.

    Checks (in order):
    1. URL contains /checkpoint, /authwall, or /captcha (security challenge)
    2. CAPTCHA iframe or element is present on the page
    3. Body text contains rate-limit phrases on error-shaped pages (throttling)

    When ``headless=False`` (or auto-detected as non-headless) and a challenge
    is detected, waits for the user to solve it in the visible browser window
    instead of raising immediately.

    The body-text heuristic only runs on pages without a ``<main>`` element
    and with short body text (<2000 chars), since real rate-limit pages are
    minimal error pages.  This avoids false positives from profile content
    that happens to contain phrases like "slow down" or "try again later".

    Raises:
        RateLimitError: If any rate-limiting or security challenge is detected
    """
    if headless is None:
        headless = _is_headless()

    current_url = page.url
    if any(
        trigger in current_url for trigger in ("/checkpoint", "/authwall", "/captcha")
    ):
        if not headless:
            await _wait_for_challenge_resolve(page)
            current_url = page.url
            if any(
                trigger in current_url
                for trigger in ("/checkpoint", "/authwall", "/captcha")
            ):
                raise RateLimitError(
                    f"LinkedIn security challenge detected. URL: {current_url}",
                    suggested_wait_time=30,
                )
            return
        raise RateLimitError(
            f"LinkedIn security challenge detected. URL: {current_url}",
            suggested_wait_time=30,
        )

    if await _has_visible_captcha(page):
        if not headless:
            await _wait_for_challenge_resolve(page)
            if await _has_visible_captcha(page):
                raise RateLimitError(
                    "CAPTCHA challenge detected on page.",
                    suggested_wait_time=60,
                )
            return
        raise RateLimitError(
            "CAPTCHA challenge detected on page.",
            suggested_wait_time=60,
        )

    try:
        has_main = await page.locator("main").count() > 0
        if has_main:
            return

        body_text = await page.locator("body").inner_text(timeout=1000)
        if body_text and len(body_text) < 2000:
            body_lower = body_text.lower()
            if any(
                phrase in body_lower
                for phrase in [
                    "too many requests",
                    "rate limit",
                    "slow down",
                    "try again later",
                ]
            ):
                raise RateLimitError(
                    "Rate limit message detected on page.",
                    suggested_wait_time=30,
                )
    except RateLimitError:
        raise
    except PlaywrightTimeoutError:
        pass


async def scroll_to_bottom(
    page: Page, pause_time: float = 1.0, max_scrolls: int = 10
) -> None:
    """Scroll to the bottom of the page to trigger lazy loading.

    Args:
        page: Patchright page object
        pause_time: Time to pause between scrolls (seconds)
        max_scrolls: Maximum number of scroll attempts
    """
    for i in range(max_scrolls):
        previous_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause_time)

        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == previous_height:
            logger.debug("Reached bottom after %d scrolls", i + 1)
            break


async def scroll_job_sidebar(
    page: Page, pause_time: float = 1.0, max_scrolls: int = 10
) -> None:
    """Scroll the job search sidebar to load all job cards.

    LinkedIn renders job search results in a scrollable sidebar container,
    not the main page body. This function finds that container by locating
    a job card link and walking up to its scrollable ancestor, then scrolls
    it iteratively until no new content loads.

    Args:
        page: Patchright page object
        pause_time: Time to pause between scrolls (seconds)
        max_scrolls: Maximum number of scroll attempts
    """
    # Wait for at least one job card link to render before scrolling
    try:
        await page.wait_for_selector('a[href*="/jobs/view/"]', timeout=5000)
    except PlaywrightTimeoutError:
        logger.debug("No job card links found, skipping sidebar scroll")
        return

    scrolled = await page.evaluate(
        """async ({pauseTime, maxScrolls}) => {
            const link = document.querySelector('a[href*="/jobs/view/"]');
            if (!link) return -2;

            let container = link.parentElement;
            while (container && container !== document.body) {
                const style = window.getComputedStyle(container);
                const overflowY = style.overflowY;
                if ((overflowY === 'auto' || overflowY === 'scroll')
                    && container.scrollHeight > container.clientHeight) {
                    break;
                }
                container = container.parentElement;
            }

            if (!container || container === document.body) {
                return -1;
            }

            let scrollCount = 0;
            for (let i = 0; i < maxScrolls; i++) {
                const prevHeight = container.scrollHeight;
                container.scrollTop = container.scrollHeight;
                await new Promise(r => setTimeout(r, pauseTime * 1000));
                if (container.scrollHeight === prevHeight) break;
                scrollCount++;
            }
            return scrollCount;
        }""",
        {"pauseTime": pause_time, "maxScrolls": max_scrolls},
    )
    if scrolled == -2:
        logger.debug("Job card link disappeared before evaluate, skipping scroll")
    elif scrolled == -1:
        logger.debug("No scrollable container found for job sidebar")
    elif scrolled:
        logger.debug("Scrolled job sidebar %d times", scrolled)
    else:
        logger.debug("Job sidebar container found but no new content loaded")


async def handle_modal_close(page: Page) -> bool:
    """Close any popup modals that might be blocking content.

    Returns:
        True if a modal was closed, False otherwise
    """
    try:
        close_button = page.locator(
            'button[aria-label="Dismiss"], '
            'button[aria-label="Close"], '
            "button.artdeco-modal__dismiss"
        ).first

        if await close_button.is_visible(timeout=1000):
            await close_button.click()
            await asyncio.sleep(0.5)
            logger.debug("Closed modal")
            return True
    except PlaywrightTimeoutError:
        pass
    except Exception as e:
        logger.debug("Error closing modal: %s", e)

    return False


def backoff_with_jitter(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_factor: float = 0.1,
) -> float:
    delay = min(base_delay * (2**attempt), max_delay)
    jitter = random.uniform(-jitter_factor * delay, jitter_factor * delay)
    return max(0, delay + jitter)


async def detect_rate_limit_post_action(page: Page) -> None:
    await asyncio.sleep(2)
    await detect_rate_limit(page)


async def expand_collapsible_sections(page: Page, max_clicks: int = 5) -> None:
    """Click all collapsed ``aria-expanded="false"`` buttons inside ``<main>``.

    LinkedIn collapses long content sections (e.g. job descriptions, experience
    details) behind a toggle button.  Clicking them reveals the full text.
    The ``aria-expanded`` attribute is locale-independent, so this works for
    any LinkedIn locale.

    Args:
        page: Patchright page object.
        max_clicks: Maximum consecutive clicks.  The method exits early when
            no button matches or becomes visible, so this is a safe cap.
    """
    for i in range(max_clicks):
        button = page.locator("main button[aria-expanded='false']")
        try:
            if await button.count() == 0:
                logger.debug("No collapsed sections after %d clicks", i)
                break
            target = button.first
            if not await target.is_visible():
                break
            await target.scroll_into_view_if_needed(timeout=2000)
            await target.click(timeout=2000)
            await asyncio.sleep(1.0)
        except PlaywrightTimeoutError:
            logger.debug("Collapsible section click timed out after %d clicks", i)
            break
        except Exception as e:
            logger.debug("Collapsible section click failed: %s", e)
            break
