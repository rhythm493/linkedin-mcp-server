from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    READ = "read"
    WRITE = "write"
    SEARCH = "search"
    ACTION = "action"


class SafetyLevel(Enum):
    SAFE = "safe"
    CAUTION = "caution"
    DESTRUCTIVE = "destructive"
    RESTRICTED = "restricted"


@dataclass
class ToolDefinition:
    name: str
    category: ToolCategory
    safety_level: SafetyLevel
    description: str = ""
    rate_limit: int = 0
    cooldown: float = 0.0
    require_confirmation: bool = False
    allowed_args: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SafetyManager:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def is_safe(self, name: str) -> bool:
        tool = self.get(name)
        if not tool:
            return True
        return tool.safety_level in (SafetyLevel.SAFE, SafetyLevel.CAUTION)

    def requires_confirmation(self, name: str) -> bool:
        tool = self.get(name)
        return tool.require_confirmation if tool else False


async def run_read_tool(
    handler: Callable[..., Awaitable[Any]],
    *args: Any,
    safety: SafetyManager | None = None,
    **kwargs: Any,
) -> Any:
    return await handler(*args, **kwargs)


async def run_write_tool(
    handler: Callable[..., Awaitable[Any]],
    *args: Any,
    safety: SafetyManager | None = None,
    **kwargs: Any,
) -> Any:
    return await handler(*args, **kwargs)
