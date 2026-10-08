"""OMDb provider: how it talks to OMDb, and that its API key stays private.

Driven through the provider's public methods. The only stub is the HTTP
transport, so the test sees the exact request the provider really sends.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.services.providers.omdb_provider import OMDbProvider

REPO_ROOT = Path(__file__).resolve().parent.parent
API_KEY = "test-omdb-key-1234"  # gitleaks:allow - fake value used only by this test

SEARCH_BODY = {
    "Response": "True",
    "Search": [{"Title": "Dune", "Year": "2021", "imdbID": "tt1160419", "Type": "movie", "Poster": "N/A"}],
}
DETAIL_BODY = {
    "Response": "True",
    "Title": "Dune",
    "Year": "2021",
    "imdbID": "tt1160419",
    "Type": "movie",
    "Released": "22 Oct 2021",
}


@pytest.fixture()
def omdb():
    """Build an OMDbProvider whose requests are captured instead of sent.

    Yields (provider, requests, respond) where `respond` sets the stubbed reply.
    """
    from app.config import settings

    requests: list[httpx.Request] = []
    reply = {"status": 200, "json": SEARCH_BODY}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(reply["status"], json=reply["json"], request=request)

    real_client = httpx.Client

    def stub_client(**kwargs):
        # Keep the provider's own base_url/timeout; only swap the network out.
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    def respond(status: int, body: dict) -> None:
        reply.update(status=status, json=body)

    with (
        patch.object(settings, "omdb_api_key", API_KEY),
        patch("app.services.providers.omdb_provider.httpx.Client", side_effect=stub_client),
    ):
        yield OMDbProvider(), requests, respond


class TestOmdbUsesHttps:
    def test_search_requests_go_over_https(self, omdb):
        provider, requests, _ = omdb

        results = provider.search("dune")

        assert [r.url.scheme for r in requests] == ["https"]
        assert [r.title for r in results] == ["Dune"]

    def test_get_details_requests_go_over_https(self, omdb):
        provider, requests, respond = omdb
        respond(200, DETAIL_BODY)

        detail = provider.get_details("tt1160419")

        assert [r.url.scheme for r in requests] == ["https"]
        assert detail is not None and detail.title == "Dune"

    def test_api_key_is_still_sent_with_each_request(self, omdb):
        """HTTPS protects the key in transit; the request must still carry it."""
        provider, requests, _ = omdb

        provider.search("dune")

        assert requests[0].url.params["apikey"] == API_KEY


class TestOmdbKeyStaysOutOfLogs:
    @pytest.mark.parametrize("call", ["search", "get_details"])
    def test_failed_request_does_not_log_the_api_key(self, omdb, caplog, call):
        """An HTTP error's text contains the full request URL, key included."""
        provider, _, respond = omdb
        respond(401, {"Response": "False", "Error": "Invalid API key!"})

        with caplog.at_level(logging.DEBUG, logger="app.services.providers.omdb_provider"):
            result = provider.search("dune") if call == "search" else provider.get_details("tt1160419")

        assert not result
        ours = [r.getMessage() for r in caplog.records if r.name == "app.services.providers.omdb_provider"]
        assert ours, "the failure should still be logged"
        assert all(API_KEY not in m for m in ours)


@pytest.mark.slow
class TestHttpClientLogsAreQuietedAtStartup:
    """httpx logs every request URL at INFO, and providers pass their API keys in
    the query string, so a freshly started process must not emit those lines.

    Checked in a fresh interpreter per entry point: this is import-time behaviour,
    so an in-process test would depend on what other tests already imported."""

    @pytest.mark.parametrize("entry_point", ["app.main", "app.celery_app", "manage"])
    def test_process_does_not_log_http_requests_at_info(self, entry_point):
        code = f"import {entry_point}, logging; log = logging.getLogger('httpx'); print(log.isEnabledFor(logging.INFO))"
        out = subprocess.run(  # noqa: S603 - fixed interpreter + constant module names, no untrusted input
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env={**os.environ, "DEBUG": "false"},
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert out.returncode == 0, out.stderr[-500:]
        assert out.stdout.strip().splitlines()[-1] == "False"
