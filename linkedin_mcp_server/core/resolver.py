from __future__ import annotations

import logging
from typing import Any
from dataclasses import dataclass, field

from linkedin_mcp_server.core.exceptions import ResolverError

logger = logging.getLogger(__name__)


@dataclass
class ResolvedEntity:
    entity_type: str
    original_value: str
    resolved_value: str
    display_name: str | None = None
    urn: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class EntityResolver:
    def __init__(self):
        self._cache: dict[str, ResolvedEntity] = {}
        self._resolve_fns: dict[str, Any] = {}

    def register(self, entity_type: str, resolve_fn: Any):
        self._resolve_fns[entity_type] = resolve_fn

    async def resolve(
        self,
        entity_type: str,
        value: str,
        use_cache: bool = True,
    ) -> ResolvedEntity:
        cache_key = f"{entity_type}:{value}"

        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        resolve_fn = self._resolve_fns.get(entity_type)
        if not resolve_fn:
            raise ResolverError(
                f"No resolver registered for entity type: {entity_type}"
            )

        try:
            result = await resolve_fn(value)
            if not result:
                raise ResolverError(f"Could not resolve {entity_type}: {value}")

            entity = ResolvedEntity(
                entity_type=entity_type,
                original_value=value,
                resolved_value=result.get("resolved_value", value),
                display_name=result.get("display_name"),
                urn=result.get("urn"),
                confidence=result.get("confidence", 1.0),
                metadata=result.get("metadata", {}),
            )

            self._cache[cache_key] = entity
            return entity

        except ResolverError:
            raise
        except Exception as e:
            raise ResolverError(f"Error resolving {entity_type}: {e}") from e

    def clear_cache(self):
        self._cache.clear()

    def get_cached(self, entity_type: str, value: str) -> ResolvedEntity | None:
        return self._cache.get(f"{entity_type}:{value}")
