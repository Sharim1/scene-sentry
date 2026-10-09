"""New movies from discovery get a release date before they are saved."""

from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent


class FakeTVDB:
    name = "tvdb"

    def __init__(self, dates):
        self.dates = dates
        self.asked = []

    def get_movie_release(self, tvdb_id):
        self.asked.append(tvdb_id)
        return self.dates.get(tvdb_id, (None, None))


class FakeRepo:
    def __init__(self, existing_tvdb_ids=()):
        self.existing = set(existing_tvdb_ids)

    def get_by_tvdb_id(self, tvdb_id, content_type=None):
        return object() if tvdb_id in self.existing else None


def _service(provider, existing=()):
    svc = ContentDiscoveryService.__new__(ContentDiscoveryService)
    svc.providers = [provider]
    svc.repo = FakeRepo(existing)
    return svc


def _movie(tvdb_id):
    return NormalizedContent(title=f"Movie {tvdb_id}", content_type="movie", provider="tvdb", tvdb_id=tvdb_id)


def test_new_movie_gets_release_date_and_year():
    provider = FakeTVDB({100: ("2019-02-06", "https://img/100.jpg")})
    item = _movie(100)

    _service(provider)._fill_new_movie_release_dates([item])

    assert item.release_date == "2019-02-06"
    assert item.year == 2019
    assert item.poster_url == "https://img/100.jpg"


def test_existing_movie_is_not_looked_up():
    provider = FakeTVDB({100: ("2019-02-06", None)})
    item = _movie(100)

    _service(provider, existing={100})._fill_new_movie_release_dates([item])

    assert provider.asked == []
    assert item.release_date is None


def test_shows_and_movies_with_a_date_are_left_alone():
    provider = FakeTVDB({})
    show = NormalizedContent(title="Show", content_type="tv_show", provider="tvdb", tvdb_id=5)
    dated = NormalizedContent(
        title="Dated", content_type="movie", provider="tvdb", tvdb_id=6, release_date="2001-01-01"
    )

    _service(provider)._fill_new_movie_release_dates([show, dated])

    assert provider.asked == []


def test_movie_with_no_date_from_tvdb_stays_undated():
    provider = FakeTVDB({})
    item = _movie(7)

    _service(provider)._fill_new_movie_release_dates([item])

    assert provider.asked == [7]
    assert item.release_date is None
