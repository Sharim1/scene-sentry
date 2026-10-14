"""Re-check of streams marked fully synced (ADR-0006, issue #75).

The report only reads; the reset only touches streams that still look wrongly ended.
Driven with fake providers and the test database.
"""

import pytest

from app.models.discovery_state import DiscoveryState
from app.services.providers.base import NormalizedContent, Page, ProviderError
from app.services.sync_recheck import recheck_streams, reset_wrong_streams
from tests.discovery_helpers import FakeProvider


class Paged(FakeProvider):
    """Catalog with `pages` pages of one title each; pages past the end are empty (exhausted).

    `filtered` pages come back empty but not exhausted. `broken` pages raise.
    """

    def __init__(self, name, pages, filtered=(), broken=()):
        super().__init__(name)
        self.pages, self.filtered, self.broken = pages, set(filtered), set(broken)
        self.asked = []

    def _page(self, page):
        self.asked.append(page)
        if page in self.broken:
            raise ProviderError(self.name, "boom")
        if page in self.filtered:
            return Page([], exhausted=False)
        if 1 <= page <= self.pages:
            return [NormalizedContent(title=f"t{page}", content_type="tv_show", provider=self.name)]
        return []

    def discover_tv_shows(self, page=1):
        return self._page(page)


def state(db_session, provider, last_page, items, synced=True, content_type="tv_show"):
    row = DiscoveryState(
        provider=provider,
        content_type=content_type,
        last_page=last_page,
        total_items_fetched=items,
        fully_synced=synced,
    )
    db_session.add(row)
    db_session.commit()
    return row


def verdicts(report):
    return {(v.provider, v.content_type): v.verdict for v in report}


def test_end_that_is_really_the_end_is_genuine(db_session):
    state(db_session, "tvdb", 3, 3)
    report = recheck_streams(db_session, [Paged("tvdb", pages=3)])
    assert verdicts(report) == {("tvdb", "tv_show"): "genuine"}


def test_source_that_still_has_pages_past_the_cursor_is_wrong(db_session):
    state(db_session, "tvmaze", 2, 2)
    report = recheck_streams(db_session, [Paged("tvmaze", pages=2, filtered={3})])
    assert verdicts(report) == {("tvmaze", "tv_show"): "wrong"}


def test_titles_past_the_cursor_are_wrong(db_session):
    state(db_session, "tvdb", 2, 2)
    report = recheck_streams(db_session, [Paged("tvdb", pages=9)])
    assert verdicts(report) == {("tvdb", "tv_show"): "wrong"}


def test_provider_that_never_lists_anything_is_reported_as_empty_catalog(db_session):
    state(db_session, "omdb", 0, 0)
    report = recheck_streams(db_session, [Paged("omdb", pages=0)])
    assert verdicts(report) == {("omdb", "tv_show"): "empty_catalog"}


def test_provider_failure_is_unknown_not_genuine(db_session):
    state(db_session, "tvdb", 3, 3)
    report = recheck_streams(db_session, [Paged("tvdb", pages=3, broken={4})])
    assert verdicts(report) == {("tvdb", "tv_show"): "unknown"}


def test_inactive_provider_is_unknown(db_session):
    state(db_session, "tvdb", 3, 3)
    assert verdicts(recheck_streams(db_session, [])) == {("tvdb", "tv_show"): "unknown"}


def test_streams_still_walking_are_not_examined(db_session):
    state(db_session, "tvdb", 3, 3, synced=False)
    assert recheck_streams(db_session, [Paged("tvdb", pages=9)]) == []


def test_report_writes_nothing(db_session):
    row = state(db_session, "tvmaze", 2, 2)
    recheck_streams(db_session, [Paged("tvmaze", pages=2, filtered={3})])
    assert not db_session.dirty and not db_session.new
    db_session.refresh(row)
    assert row.fully_synced is True and row.last_page == 2


class TestReset:
    def test_wrong_stream_is_unsynced_and_keeps_its_cursor(self, db_session):
        row = state(db_session, "tvmaze", 42, 458)
        done = reset_wrong_streams(db_session, [Paged("tvmaze", pages=50)], [("tvmaze", "tv_show")])
        assert done == [("tvmaze", "tv_show")]
        db_session.refresh(row)
        assert row.fully_synced is False
        assert (row.last_page, row.total_items_fetched) == (42, 458)

    def test_genuine_stream_is_refused_and_left_alone(self, db_session):
        row = state(db_session, "tvdb", 3, 3)
        done = reset_wrong_streams(db_session, [Paged("tvdb", pages=3)], [("tvdb", "tv_show")])
        assert done == []
        db_session.refresh(row)
        assert row.fully_synced is True

    def test_unknown_stream_is_refused(self, db_session):
        row = state(db_session, "tvdb", 3, 3)
        done = reset_wrong_streams(db_session, [Paged("tvdb", pages=3, broken={4})], [("tvdb", "tv_show")])
        assert done == []
        db_session.refresh(row)
        assert row.fully_synced is True

    def test_only_named_streams_are_reset(self, db_session):
        a = state(db_session, "tvmaze", 2, 2)
        b = state(db_session, "tvdb", 2, 2)
        providers = [Paged("tvmaze", pages=9), Paged("tvdb", pages=9)]
        reset_wrong_streams(db_session, providers, [("tvmaze", "tv_show")])
        db_session.refresh(a)
        db_session.refresh(b)
        assert (a.fully_synced, b.fully_synced) == (False, True)

    def test_unknown_stream_name_is_an_error(self, db_session):
        with pytest.raises(ValueError):
            reset_wrong_streams(db_session, [], [("nope", "tv_show")])

    def test_reset_stream_is_walked_to_the_real_end_by_the_fixed_walker(self, db_session):
        from unittest.mock import patch

        from app.services.content_discovery import ContentDiscoveryService

        row = state(db_session, "tvmaze", 2, 2)
        prov = Paged("tvmaze", pages=6, filtered={3, 4})
        reset_wrong_streams(db_session, [prov], [("tvmaze", "tv_show")])
        svc = ContentDiscoveryService(db_session)
        svc.providers = [prov]
        with patch("app.services.content_discovery.settings.discovery_batch_size", 10):
            svc.run_scheduled_sync()
        db_session.refresh(row)
        assert row.fully_synced is True
        assert row.last_page == 6
        assert row.total_items_fetched == 4  # pages 5 and 6 added to the 2 already counted
