"""A provider failure during a catalog walk is a failure, never "no more pages".

Driven through the scheduled sync with a fake provider and the real test database.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from app.models.discovery_state import DiscoveryState
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent, ProviderError


class FlakyProvider:
    """Paged catalog where listed pages raise ProviderError; pages past the end are empty."""

    name = "tvdb"

    def __init__(self, pages, failing=()):
        self.pages = list(pages)
        self.failing = set(failing)

    def _page(self, page):
        if page in self.failing:
            raise ProviderError("tvdb", "timeout")
        return list(self.pages[page - 1]) if 0 < page <= len(self.pages) else []

    def discover_movies(self, page=1):
        return self._page(page)

    def discover_tv_shows(self, page=1):
        return []


def titles(*ids):
    return [NormalizedContent(title=f"movie {i}", content_type="movie", provider="tvdb", tvdb_id=i) for i in ids]


def seed(db_session, *, last_page, fully_synced):
    db_session.add(
        DiscoveryState(
            provider="tvdb",
            content_type="movie",
            last_page=last_page,
            total_items_fetched=0,
            fully_synced=fully_synced,
            last_synced_at=datetime.now(UTC),
        )
    )
    db_session.commit()


def run(db_session, provider, batch=5):
    svc = ContentDiscoveryService(db_session)
    svc.providers = [provider]
    with patch("app.services.content_discovery.settings.discovery_batch_size", batch):
        svc.run_scheduled_sync()
    db_session.expire_all()
    return db_session.query(DiscoveryState).filter_by(provider="tvdb", content_type="movie").one()


def test_failure_on_page_n_leaves_cursor_at_n_minus_1_and_not_fully_synced(db_session):
    seed(db_session, last_page=1, fully_synced=False)
    state = run(db_session, FlakyProvider([titles(1), titles(2), titles(3)], failing={3}))
    assert state.last_page == 2
    assert state.fully_synced is False


def test_failure_on_the_first_page_of_a_fresh_stream_does_not_finish_it(db_session):
    state = run(db_session, FlakyProvider([titles(1)], failing={1}))
    assert state.last_page == 0
    assert state.fully_synced is False


def test_next_run_resumes_from_the_page_that_failed(db_session):
    seed(db_session, last_page=1, fully_synced=False)
    provider = FlakyProvider([titles(1), titles(2), titles(3)], failing={2})
    run(db_session, provider)

    provider.failing.clear()
    state = run(db_session, provider)

    assert state.last_page == 3
    assert state.fully_synced is True


def test_failure_leaves_a_fully_synced_stream_fully_synced(db_session):
    seed(db_session, last_page=2, fully_synced=True)
    state = run(db_session, FlakyProvider([titles(1), titles(2), titles(3)], failing={3}))
    assert state.last_page == 2
    assert state.fully_synced is True


def test_confirmed_empty_page_after_non_empty_pages_marks_fully_synced(db_session):
    state = run(db_session, FlakyProvider([titles(1), titles(2)]))
    assert state.last_page == 2
    assert state.fully_synced is True


def _mock_http(handler):
    real_client = httpx.Client

    def stub_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return stub_client


class TestProvidersRaiseInsteadOfReturningEmpty:
    def test_tmdb_discover_raises_on_http_error(self):
        from app.config import settings
        from app.services.providers.tmdb_provider import TMDbProvider

        stub = _mock_http(lambda request: httpx.Response(429, request=request))
        with (
            patch.object(settings, "tmdb_api_key", "fake-key"),
            patch("app.services.providers.tmdb_provider.httpx.Client", side_effect=stub),
        ):
            provider = TMDbProvider()
            with pytest.raises(ProviderError):
                provider.discover_movies(page=1)
            with pytest.raises(ProviderError):
                provider.discover_tv_shows(page=1)

    def test_tmdb_discover_empty_results_is_a_normal_empty_page(self):
        from app.config import settings
        from app.services.providers.tmdb_provider import TMDbProvider

        stub = _mock_http(lambda request: httpx.Response(200, json={"results": []}, request=request))
        with (
            patch.object(settings, "tmdb_api_key", "fake-key"),
            patch("app.services.providers.tmdb_provider.httpx.Client", side_effect=stub),
        ):
            assert TMDbProvider().discover_movies(page=9) == []

    def test_tvdb_discover_raises_when_the_client_fails(self):
        from app.services.providers.tvdb_provider import TVDBProvider

        class Broken:
            def get_all_movies(self, page=0):
                raise TimeoutError("slow")

            def get_all_series(self, page=0):
                raise TimeoutError("slow")

        provider = TVDBProvider()
        provider.client = Broken()
        with pytest.raises(ProviderError):
            provider.discover_movies(page=1)
        with pytest.raises(ProviderError):
            provider.discover_tv_shows(page=1)

    def _tvmaze(self, status, json=None):
        from app.services.providers.tvmaze_provider import TVMazeProvider

        provider = TVMazeProvider()
        provider._client = httpx.Client(
            base_url="https://api.tvmaze.com",
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=json, request=request)),
        )
        provider._rate_limit = lambda: None
        return provider

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_tvmaze_discover_raises_on_http_failure(self, status):
        with pytest.raises(ProviderError):
            self._tvmaze(status).discover_tv_shows(page=1)

    def test_tvmaze_discover_raises_on_a_non_list_body(self):
        with pytest.raises(ProviderError):
            self._tvmaze(200, json={"oops": 1}).discover_tv_shows(page=1)

    def test_tvmaze_404_past_the_last_page_is_the_end_of_the_catalog(self):
        assert self._tvmaze(404).discover_tv_shows(page=999) == []
