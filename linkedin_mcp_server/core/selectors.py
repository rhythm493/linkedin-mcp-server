from __future__ import annotations

import logging
from dataclasses import dataclass, field

from linkedin_mcp_server.core.exceptions import SelectorError

logger = logging.getLogger(__name__)


@dataclass
class Selector:
    css: str | None = None
    xpath: str | None = None
    text: str | None = None
    role: str | None = None
    label: str | None = None
    test_id: str | None = None
    placeholder: str | None = None

    def __post_init__(self):
        if not any(
            [
                self.css,
                self.xpath,
                self.text,
                self.role,
                self.label,
                self.test_id,
                self.placeholder,
            ]
        ):
            raise SelectorError("At least one selector strategy must be provided")


@dataclass
class SelectorChain:
    selectors: list[Selector] = field(default_factory=list)
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0

    def add(self, selector: Selector) -> SelectorChain:
        self.selectors.append(selector)
        return self

    def with_timeout(self, timeout: float) -> SelectorChain:
        self.timeout = timeout
        return self

    def with_retries(self, count: int, delay: float = 1.0) -> SelectorChain:
        self.retry_count = count
        self.retry_delay = delay
        return self
