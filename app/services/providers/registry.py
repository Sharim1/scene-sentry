"""
Provider registry — returns the list of enabled and configured providers
based on feature flags and API key availability in settings.
"""
from __future__ import annotations

import logging
from typing import List

from app.config import settings
from app.services.providers.base import ContentProvider

logger = logging.getLogger(__name__)


def get_active_providers() -> List[ContentProvider]:
    """Instantiate and return only providers that are both enabled and usable."""
    providers: List[ContentProvider] = []

    if settings.tvmaze_enabled:
        from app.services.providers.tvmaze_provider import TVMazeProvider
        providers.append(TVMazeProvider())
        logger.debug("TVMaze provider active")

    if settings.tvdb_enabled and settings.tvdb_api_key:
        from app.services.providers.tvdb_provider import TVDBProvider
        p = TVDBProvider()
        if p.client is not None:
            providers.append(p)
            logger.debug("TVDB provider active")

    if settings.omdb_enabled and settings.omdb_api_key:
        from app.services.providers.omdb_provider import OMDbProvider
        providers.append(OMDbProvider())
        logger.debug("OMDb provider active")

    if settings.tmdb_enabled and settings.tmdb_api_key:
        from app.services.providers.tmdb_provider import TMDbProvider
        providers.append(TMDbProvider())
        logger.debug("TMDb provider active")

    if not providers:
        logger.warning("No content providers are active — content pages will be empty")

    return providers
