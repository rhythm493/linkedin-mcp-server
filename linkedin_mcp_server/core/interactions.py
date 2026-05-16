from __future__ import annotations

import logging
from typing import Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Interaction:
    action: str
    target: str
    element: Any = None
    page: Any = None
    context: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    success: bool = True
    error: str | None = None
    screenshot: str | None = None


class InteractionTracker:
    def __init__(self, max_history: int = 1000):
        self.history: list[Interaction] = []
        self.max_history = max_history

    def record(
        self,
        action: str,
        target: str,
        element: Any = None,
        page: Any = None,
        context: dict[str, Any] | None = None,
    ):
        interaction = Interaction(
            action=action,
            target=target,
            element=element,
            page=page,
            context=context or {},
        )
        self.history.append(interaction)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]
        return interaction

    def last(self, action: str | None = None) -> Interaction | None:
        if action is None:
            return self.history[-1] if self.history else None
        for interaction in reversed(self.history):
            if interaction.action == action:
                return interaction
        return None

    def recent(self, n: int = 5) -> list[Interaction]:
        return self.history[-n:]

    def count(self, action: str) -> int:
        return sum(1 for i in self.history if i.action == action)

    def clear(self):
        self.history.clear()

    @property
    def total(self) -> int:
        return len(self.history)

    @property
    def failures(self) -> list[Interaction]:
        return [i for i in self.history if not i.success]
