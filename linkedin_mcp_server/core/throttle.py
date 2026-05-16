from __future__ import annotations

import random
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveThrottle:
    min_delay: float = 1.0
    max_delay: float = 5.0
    multiplier: float = 1.5
    window_size: int = 10
    error_threshold: float = 0.3
    recent_times: list[float] = field(default_factory=list)
    recent_errors: list[bool] = field(default_factory=list)
    current_delay: float = 1.0

    def record_request(self, duration: float, had_error: bool = False):
        self.recent_times.append(duration)
        self.recent_errors.append(had_error)

        if len(self.recent_times) > self.window_size:
            self.recent_times.pop(0)
            self.recent_errors.pop(0)

        if len(self.recent_errors) >= 3:
            error_rate = sum(self.recent_errors[-3:]) / min(3, len(self.recent_errors))
            if error_rate > self.error_threshold:
                self.current_delay = min(
                    self.current_delay * self.multiplier, self.max_delay
                )
            elif error_rate == 0 and self.current_delay > self.min_delay:
                self.current_delay = max(
                    self.current_delay / self.multiplier, self.min_delay
                )

    def get_delay(self, last_duration: float) -> float:
        jitter = random.uniform(-0.5, 0.5)
        if last_duration < 0.5:
            return max(0.1, self.current_delay + jitter)
        return max(0.1, min(last_duration * 2, self.max_delay))

    def reset(self):
        self.current_delay = self.min_delay
        self.recent_times.clear()
        self.recent_errors.clear()
