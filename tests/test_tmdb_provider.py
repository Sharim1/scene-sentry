"""TMDb provider: its API key (a query parameter) must stay out of the logs."""

import logging
from unittest.mock import patch

import httpx

from app.services.providers.tmdb_provider import TMDbProvider

API_KEY = "test-tmdb-key-5678"  # gitleaks:allow - fake value used only by this test


def test_failed_request_does_not_log_the_api_key(caplog):
    """An HTTP error's text contains the full request URL, key included."""
    from app.config import settings

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status_message": "Invalid API key"}, request=request)

    real_client = httpx.Client

    def stub_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    with (
        patch.object(settings, "tmdb_api_key", API_KEY),
        patch("app.services.providers.tmdb_provider.httpx.Client", side_effect=stub_client),
        caplog.at_level(logging.DEBUG, logger="app.services.providers.tmdb_provider"),
    ):
        results = TMDbProvider().search("dune")

    assert results == []
    ours = [r.getMessage() for r in caplog.records if r.name == "app.services.providers.tmdb_provider"]
    assert any("TMDb API error" in m for m in ours), "the failure should still be logged"
    assert all(API_KEY not in m for m in ours)
