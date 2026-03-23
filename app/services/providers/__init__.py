"""
Content provider abstraction layer.

Each provider normalises its API responses into `NormalizedContent` so the
discovery service can aggregate, deduplicate, and persist data from any
combination of enabled platforms.
"""
from app.services.providers.base import ContentProvider, NormalizedContent
from app.services.providers.registry import get_active_providers

__all__ = ["ContentProvider", "NormalizedContent", "get_active_providers"]
