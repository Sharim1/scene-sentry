"""Shared fakes for tests that drive ContentDiscoveryService through its public sync."""

from app.models.content import Content
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent


class FakeProvider:
    """One page of titles per content type, then empty."""

    def __init__(self, name, movies=(), shows=()):
        self.name = name
        self._movies = list(movies)
        self._shows = list(shows)
        self.asked_release = []

    def discover_movies(self, page=1):
        return list(self._movies) if page == 1 else []

    def discover_tv_shows(self, page=1):
        return list(self._shows) if page == 1 else []


class FakeTVDBWithDates(FakeProvider):
    """A TVDB stand-in that can answer the per-movie release-date lookup."""

    def __init__(self, dates, **kw):
        super().__init__("tvdb", **kw)
        self.dates = dates

    def get_movie_release(self, tvdb_id):
        self.asked_release.append(tvdb_id)
        return self.dates.get(tvdb_id, (None, None))


def item(title, content_type, provider="tvdb", year=2015, **ids):
    return NormalizedContent(title=title, content_type=content_type, provider=provider, year=year, **ids)


def sync(db_session, *providers):
    svc = ContentDiscoveryService(db_session)
    svc.providers = list(providers)
    svc.run_scheduled_sync()


def stored(db_session, content_type=None):
    db_session.expire_all()
    query = db_session.query(Content)
    if content_type:
        query = query.filter(Content.content_type == content_type)
    return query.all()


def provider_with(content_type, name, items):
    return FakeProvider(name, movies=items) if content_type == "movie" else FakeProvider(name, shows=items)
