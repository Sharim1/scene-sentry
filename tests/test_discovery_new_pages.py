"""A provider that is "fully synced" must still pick up titles added after we synced.

TVDB lists titles oldest first, so new titles are appended on pages *after* the
last one we saw. Driven through the service's public sync methods, with a real
test database and a fake provider that behaves like TVDB (append-only pages).
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.models.content import Content
from app.models.discovery_state import DiscoveryState
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent


class FakeTVDB:
    """Append-only paged catalog: page N holds a fixed list; pages past the end are empty."""

    name = "tvdb"

    def __init__(self, movie_pages=(), show_pages=()):
        self.movie_pages = list(movie_pages)
        self.show_pages = list(show_pages)
        self.requested: list[tuple[str, int]] = []

    def discover_movies(self, page=1):
        self.requested.append(("movie", page))
        return list(self.movie_pages[page - 1]) if 0 < page <= len(self.movie_pages) else []

    def discover_tv_shows(self, page=1):
        self.requested.append(("tv_show", page))
        return list(self.show_pages[page - 1]) if 0 < page <= len(self.show_pages) else []


def title(tvdb_id: int, content_type: str) -> NormalizedContent:
    return NormalizedContent(
        title=f"{content_type} {tvdb_id}", content_type=content_type, provider="tvdb", tvdb_id=tvdb_id
    )


def pages(content_type: str, *id_groups: list[int]):
    return [[title(i, content_type) for i in ids] for ids in id_groups]


def service(db_session, provider) -> ContentDiscoveryService:
    svc = ContentDiscoveryService(db_session)
    svc.providers = [provider]
    return svc


def seed_state(db_session, content_type: str, *, last_page: int, fully_synced: bool) -> None:
    db_session.add(
        DiscoveryState(
            provider="tvdb",
            content_type=content_type,
            last_page=last_page,
            total_items_fetched=last_page * 2,
            fully_synced=fully_synced,
            last_synced_at=datetime.now(UTC),
        )
    )
    db_session.commit()


def state(db_session, content_type: str) -> DiscoveryState:
    db_session.expire_all()
    return db_session.query(DiscoveryState).filter_by(provider="tvdb", content_type=content_type).one()


def saved_ids(db_session, content_type: str) -> set[int]:
    db_session.expire_all()
    rows = db_session.query(Content.tvdb_id).filter(Content.content_type == content_type).all()
    return {r[0] for r in rows}


@pytest.mark.parametrize("content_type", ["movie", "tv_show"])
class TestFullySyncedProviderPicksUpNewPages:
    def _provider(self, content_type, *groups):
        built = pages(content_type, *groups)
        return FakeTVDB(movie_pages=built) if content_type == "movie" else FakeTVDB(show_pages=built)

    def test_titles_appended_after_the_last_synced_page_are_saved(self, db_session, content_type):
        seed_state(db_session, content_type, last_page=2, fully_synced=True)
        provider = self._provider(content_type, [1, 2], [3, 4], [5, 6], [7, 8])  # pages 3 and 4 are new

        service(db_session, provider).run_scheduled_sync()

        assert {5, 6, 7, 8} <= saved_ids(db_session, content_type)

    def test_the_saved_position_moves_forward_and_it_stays_fully_synced(self, db_session, content_type):
        seed_state(db_session, content_type, last_page=2, fully_synced=True)
        provider = self._provider(content_type, [1, 2], [3, 4], [5, 6], [7, 8])

        service(db_session, provider).run_scheduled_sync()

        current = state(db_session, content_type)
        assert current.last_page == 4
        assert current.fully_synced is True

    def test_nothing_new_saves_nothing_and_keeps_the_position(self, db_session, content_type):
        seed_state(db_session, content_type, last_page=2, fully_synced=True)
        provider = self._provider(content_type, [1, 2], [3, 4])

        service(db_session, provider).run_scheduled_sync()

        current = state(db_session, content_type)
        assert current.last_page == 2
        assert current.fully_synced is True

    def test_a_run_reads_no_more_pages_than_the_batch_size(self, db_session, content_type):
        seed_state(db_session, content_type, last_page=1, fully_synced=True)
        provider = self._provider(content_type, [1, 2], [3, 4], [5, 6], [7, 8], [9, 10])  # 4 new pages

        with patch("app.services.content_discovery.settings.discovery_batch_size", 2):
            service(db_session, provider).run_scheduled_sync()

        assert state(db_session, content_type).last_page == 3  # advanced by the batch size, not all 4
        assert saved_ids(db_session, content_type) >= {3, 4, 5, 6}
        assert 9 not in saved_ids(db_session, content_type)

    def test_the_first_page_is_still_refreshed(self, db_session, content_type):
        """Sources whose first page shows the newest titles rely on this."""
        seed_state(db_session, content_type, last_page=1, fully_synced=True)
        provider = self._provider(content_type, [1, 2])
        provider_pages = pages(content_type, [1, 2, 99])  # page 1 now carries a brand-new title
        if content_type == "movie":
            provider.movie_pages = provider_pages
        else:
            provider.show_pages = provider_pages

        service(db_session, provider).run_scheduled_sync()

        assert 99 in saved_ids(db_session, content_type)


@pytest.mark.parametrize("content_type", ["movie", "tv_show"])
class TestNotYetSyncedProviderStillResumesAndFinishes:
    def test_resumes_from_the_saved_page_and_marks_itself_synced_at_the_end(self, db_session, content_type):
        seed_state(db_session, content_type, last_page=1, fully_synced=False)
        built = pages(content_type, [1, 2], [3, 4], [5, 6])
        provider = FakeTVDB(movie_pages=built) if content_type == "movie" else FakeTVDB(show_pages=built)

        with patch("app.services.content_discovery.settings.discovery_batch_size", 10):
            service(db_session, provider).run_scheduled_sync()

        assert {3, 4, 5, 6} <= saved_ids(db_session, content_type)
        current = state(db_session, content_type)
        assert current.last_page == 3
        assert current.fully_synced is True
