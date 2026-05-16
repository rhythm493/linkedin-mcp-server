"""Custom exceptions for LinkedIn scraping operations."""


class LinkedInScraperException(Exception):
    """Base exception for LinkedIn scraper."""

    pass


class AuthenticationError(LinkedInScraperException):
    """Raised when authentication fails."""

    pass


class RateLimitError(LinkedInScraperException):
    """Raised when rate limiting is detected."""

    def __init__(self, message: str, suggested_wait_time: int = 300):
        super().__init__(message)
        self.suggested_wait_time = suggested_wait_time


class ElementNotFoundError(LinkedInScraperException):
    """Raised when an expected element is not found."""

    pass


class ProfileNotFoundError(LinkedInScraperException):
    """Raised when a profile/page returns 404."""

    pass


class NetworkError(LinkedInScraperException):
    """Raised when network-related issues occur."""

    pass


class ScrapingError(LinkedInScraperException):
    """Raised when scraping fails for various reasons."""

    pass


class InteractionError(LinkedInScraperException):
    """Raised when a page interaction fails."""

    pass


class SelectorError(LinkedInScraperException):
    """Raised when element selection fails."""

    pass


class ResolverError(LinkedInScraperException):
    """Raised when entity resolution fails."""

    pass


class ConcurrencyError(LinkedInScraperException):
    """Raised when concurrent operations exceed limits."""

    pass


class QuotaExceededError(LinkedInScraperException):
    """Raised when usage quota is exceeded."""

    pass
