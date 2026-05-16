from __future__ import annotations

from typing import Any, Generic, TypeVar
from dataclasses import dataclass, field
from datetime import datetime

T = TypeVar("T")


@dataclass
class ToolResponse(Generic[T]):
    success: bool = True
    data: T | None = None
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def ok(cls, data: T, **metadata) -> ToolResponse[T]:
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, error_type: str | None = None) -> ToolResponse[T]:
        return cls(success=False, error=error, error_type=error_type)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": self.success,
            "timestamp": self.timestamp,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        if self.error_type:
            result["error_type"] = self.error_type
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def __bool__(self) -> bool:
        return self.success
