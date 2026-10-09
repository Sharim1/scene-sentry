"""Discovery must not merge titles that are genuinely different.

Driven through the service's public sync with fake providers and a real test
database. Titles in non-Latin scripts used to normalise to an empty string, so every
such title of a given year and type shared one dedup key and all but the first were
dropped. Titles that really are the same across providers must still merge.
"""

import pytest

from app.models.content import Content
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent


class FakeProvider:
    """One page of titles per content type, then empty."""

    def __init__(self, name, movies=(), shows=()):
        self.name = name
        self._movies = list(movies)
        self._shows = list(shows)

    def discover_movies(self, page=1):
        return list(self._movies) if page == 1 else []

    def discover_tv_shows(self, page=1):
        return list(self._shows) if page == 1 else []


def item(title, content_type, provider="tvdb", year=2015, **ids):
    return NormalizedContent(title=title, content_type=content_type, provider=provider, year=year, **ids)


def sync(db_session, *providers):
    svc = ContentDiscoveryService(db_session)
    svc.providers = list(providers)
    svc.run_scheduled_sync()


def stored(db_session, content_type):
    db_session.expire_all()
    return db_session.query(Content).filter(Content.content_type == content_type).all()


def provider_with(content_type, name, items):
    return FakeProvider(name, movies=items) if content_type == "movie" else FakeProvider(name, shows=items)


@pytest.mark.parametrize("content_type", ["movie", "tv_show"])
class TestDistinctTitlesAreKept:
    def test_titles_in_different_non_latin_scripts_from_one_year_are_all_stored(self, db_session, content_type):
        titles = ["一把青", "달콤한 유혹", "偽装の夫婦", "Все сокровища мира", "แม่ยายที่รัก", "అమృతం"]
        items = [item(t, content_type, tvdb_id=100 + i) for i, t in enumerate(titles)]

        sync(db_session, provider_with(content_type, "tvdb", items))

        assert {r.title for r in stored(db_session, content_type)} == set(titles)

    def test_titles_that_normalise_to_nothing_are_not_merged(self, db_session, content_type):
        items = [item("!!!", content_type, tvdb_id=1), item("???", content_type, tvdb_id=2)]

        sync(db_session, provider_with(content_type, "tvdb", items))

        assert {r.tvdb_id for r in stored(db_session, content_type)} == {1, 2}


@pytest.mark.parametrize("content_type", ["movie", "tv_show"])
class TestSameTitleAcrossProvidersStillMerges:
    def test_a_tvdb_title_and_an_id_less_tmdb_title_with_the_same_name_and_year_become_one_row(
        self, db_session, content_type
    ):
        tvdb = provider_with(content_type, "tvdb", [item("Silo", content_type, tvdb_id=5, year=2023)])
        tmdb = provider_with(content_type, "tmdb", [item("Silo", content_type, provider="tmdb", year=2023, tmdb_id=99)])

        sync(db_session, tvdb, tmdb)

        rows = stored(db_session, content_type)
        assert len(rows) == 1
        assert (rows[0].tvdb_id, rows[0].tmdb_id) == (5, 99)

    def test_accents_do_not_stop_a_match(self, db_session, content_type):
        tvdb = provider_with(content_type, "tvdb", [item("Café Society", content_type, tvdb_id=7, year=2016)])
        tmdb = provider_with(
            content_type, "tmdb", [item("Cafe Society", content_type, provider="tmdb", year=2016, tmdb_id=8)]
        )

        sync(db_session, tvdb, tmdb)

        assert len(stored(db_session, content_type)) == 1


class TestTitleKey:
    def test_different_kana_do_not_share_a_key(self):
        """Dakuten/handakuten matter: パパ and ハハ are different words."""
        a = item("パパ", "movie", year=2020).dedup_key
        b = item("ハハ", "movie", year=2020).dedup_key
        assert a != b

    def test_accented_and_plain_latin_share_a_key(self):
        assert item("Café", "movie", year=2020).dedup_key == item("Cafe", "movie", year=2020).dedup_key
