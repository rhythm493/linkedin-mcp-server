from __future__ import annotations

import time
from typing import Any
from dataclasses import dataclass, field


@dataclass
class Timer:
    start: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.start

    def reset(self) -> Timer:
        self.start = time.time()
        return self

    @property
    def seconds(self) -> float:
        return self.elapsed()

    def __enter__(self) -> Timer:
        self.start = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class TimingStats:
    def __init__(self):
        self._measurements: dict[str, list[float]] = {}

    def record(self, operation: str, duration: float):
        if operation not in self._measurements:
            self._measurements[operation] = []
        self._measurements[operation].append(duration)

    def average(self, operation: str) -> float:
        measurements = self._measurements.get(operation, [])
        return sum(measurements) / len(measurements) if measurements else 0.0

    def max(self, operation: str) -> float:
        measurements = self._measurements.get(operation, [])
        return max(measurements) if measurements else 0.0

    def min(self, operation: str) -> float:
        measurements = self._measurements.get(operation, [])
        return min(measurements) if measurements else 0.0

    def count(self, operation: str) -> int:
        return len(self._measurements.get(operation, []))

    def clear(self):
        self._measurements.clear()
