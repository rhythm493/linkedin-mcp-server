from __future__ import annotations

from typing import Any
from datetime import datetime


def serialize_datetime(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def clean_none(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in obj.items() if v is not None}


def safe_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current if current is not None else default
