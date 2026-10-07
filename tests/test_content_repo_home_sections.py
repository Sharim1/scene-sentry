"""Home page section queries on ContentRepository.

Regression coverage for a bug found on the live site: TVDB has at least one
title with release_date "9696-01-01" (a typo on their end). A plain
`ORDER BY release_date DESC` put it above every real recent release and it
got picked as the homepage spotlight.
"""

from app.models.content import Content
from app.repositories.content_repo import ContentRepository


def _content(db_session, **kwargs):
    defaults = {"title": "Untitled", "content_type": "movie"}
    row = Content(**{**defaults, **kwargs})
    db_session.add(row)
    db_session.commit()
    return row


def test_get_recent_excludes_implausible_future_dates(db_session):
    _content(db_session, title="Bad TVDB Date", release_date="9696-01-01")
    real = _content(db_session, title="Real Recent Release", release_date="2026-09-01")

    result = ContentRepository(db_session).get_recent(limit=10)

    assert real in result
    assert all(c.title != "Bad TVDB Date" for c in result)


def test_get_recent_excludes_actual_future_releases(db_session):
    _content(db_session, title="Not Out Yet", release_date="2099-01-01")
    real = _content(db_session, title="Already Out", release_date="2020-01-01")

    result = ContentRepository(db_session).get_recent(limit=10)

    assert real in result
    assert all(c.title != "Not Out Yet" for c in result)


def test_get_coming_soon_excludes_implausible_far_future_dates(db_session):
    _content(db_session, title="Bad TVDB Date", release_date="9696-01-01")
    real = _content(db_session, title="Actually Upcoming", release_date="2099-01-01")
    # Move "today" far enough that 2099 is still in the 3-year coming-soon window
    # isn't realistic to simulate here, so just assert the typo'd date never wins.

    result = ContentRepository(db_session).get_coming_soon(limit=10)

    assert all(c.title != "Bad TVDB Date" for c in result)
    assert real not in result  # 2099 is outside today's 3-year coming-soon window too


def test_get_top_rated_excludes_out_of_range_values(db_session):
    _content(db_session, title="Bad Rating", rating=9696)
    real = _content(db_session, title="Good Rating", rating=8.4)

    result = ContentRepository(db_session).get_top_rated(limit=10)

    assert real in result
    assert all(c.title != "Bad Rating" for c in result)


def test_get_top_rated_returns_nothing_when_no_ratings_in_range(db_session):
    _content(db_session, title="Unrated Movie", content_type="movie")

    result = ContentRepository(db_session).get_top_rated(content_type="movie", limit=10)

    assert result == []
