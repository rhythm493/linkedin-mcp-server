"""Core browser management, authentication, and scraping utilities."""

from .auth import (
    detect_auth_barrier,
    detect_auth_barrier_quick,
    is_logged_in,
    resolve_remember_me_prompt,
    wait_for_manual_login,
    warm_up_browser,
)
from .browser import BrowserManager
from .exceptions import (
    AuthenticationError,
    ConcurrencyError,
    ElementNotFoundError,
    InteractionError,
    LinkedInScraperException,
    NetworkError,
    ProfileNotFoundError,
    QuotaExceededError,
    RateLimitError,
    ResolverError,
    ScrapingError,
    SelectorError,
)
from .utils import (
    backoff_with_jitter,
    detect_rate_limit,
    detect_rate_limit_post_action,
    handle_modal_close,
    scroll_to_bottom,
    scroll_job_sidebar,
)

__all__ = [
    "AuthenticationError",
    "backoff_with_jitter",
    "BrowserManager",
    "ConcurrencyError",
    "detect_auth_barrier",
    "detect_auth_barrier_quick",
    "detect_rate_limit",
    "detect_rate_limit_post_action",
    "ElementNotFoundError",
    "handle_modal_close",
    "InteractionError",
    "is_logged_in",
    "LinkedInScraperException",
    "NetworkError",
    "ProfileNotFoundError",
    "QuotaExceededError",
    "RateLimitError",
    "ResolverError",
    "resolve_remember_me_prompt",
    "ScrapingError",
    "scroll_job_sidebar",
    "scroll_to_bottom",
    "SelectorError",
    "wait_for_manual_login",
    "warm_up_browser",
]
