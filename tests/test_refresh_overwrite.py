"""A refresh replaces provider-owned fields with newer values.

Driven through ContentDiscoveryService.enrich_sparse_content with a fake provider and
the in-memory test database: no network.
"""

from datetime import UTC, datetime

from app.models.content import Content
from app.models.episode import Episode
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent, NormalizedEpisode


class FakeShowProvider:
    name = "tvmaze"

    def __init__(self, detail, episodes=()):
        self.detail = detail
        self.episodes = list(episodes)

    def get_details(self, ext_id):
        return self.detail

    def get_episodes(self, ext_id):
        return self.episodes


def add_show(db_session, **fields):
    row = Content(title="Show", content_type="tv_show", tvmaze_id=7, **fields)
    db_session.add(row)
    db_session.commit()
    return row


def refresh(db_session, provider):
    svc = ContentDiscoveryService(db_session)
    svc.providers = [provider]
    svc.enrich_sparse_content(batch_size=10, now=datetime(2026, 10, 15, tzinfo=UTC))
    db_session.expire_all()


def test_refresh_replaces_show_status_and_rating(db_session):
    show = add_show(db_session, status="Running", rating=7.0)
    detail = NormalizedContent(title="Show", content_type="tv_show", provider="tvmaze", status="Ended", rating=8.4)

    refresh(db_session, FakeShowProvider(detail))

    show = db_session.get(Content, show.id)
    assert show.status == "Ended"
    assert show.rating == 8.4


def test_refresh_replaces_a_rescheduled_episode_air_date(db_session):
    show = add_show(db_session)
    db_session.add(Episode(content_id=show.id, season_number=1, episode_number=1, air_date="2026-11-01", rating=6.0))
    db_session.commit()
    detail = NormalizedContent(title="Show", content_type="tv_show", provider="tvmaze")
    moved = NormalizedEpisode(title="E1", season_number=1, episode_number=1, air_date="2026-11-15", rating=7.5)

    refresh(db_session, FakeShowProvider(detail, [moved]))

    episode = db_session.query(Episode).filter_by(content_id=show.id).one()
    assert episode.air_date == "2026-11-15"
    assert episode.rating == 7.5


def test_a_hand_edited_title_is_not_overwritten(db_session):
    show = add_show(db_session, status="Running", rating=7.0, refresh_locked=True)
    db_session.add(Episode(content_id=show.id, season_number=1, episode_number=1, air_date="2026-11-01"))
    db_session.commit()
    detail = NormalizedContent(title="Show", content_type="tv_show", provider="tvmaze", status="Ended", rating=8.4)
    moved = NormalizedEpisode(title="E1", season_number=1, episode_number=1, air_date="2026-11-15")

    refresh(db_session, FakeShowProvider(detail, [moved]))

    show = db_session.get(Content, show.id)
    assert (show.status, show.rating) == ("Running", 7.0)
    episode = db_session.query(Episode).filter_by(content_id=show.id).one()
    assert episode.air_date == "2026-11-01"


def test_a_missing_value_from_the_provider_keeps_the_stored_one(db_session):
    show = add_show(db_session, status="Running", rating=7.0)
    detail = NormalizedContent(title="Show", content_type="tv_show", provider="tvmaze")

    refresh(db_session, FakeShowProvider(detail))

    show = db_session.get(Content, show.id)
    assert (show.status, show.rating) == ("Running", 7.0)
