"""Provider delete and merge notices (ADR-0006, issue #87).

Driven through apply_notices with fake notices and the in-memory test database: no network,
no real database.
"""

import logging
from datetime import UTC, datetime

from app.models.content import Content
from app.models.episode import Episode
from app.models.external_id import ContentExternalId
from app.models.gossip import Gossip
from app.models.library import LibraryItem, WatchStatus
from app.models.ranking import UserContentRank
from app.models.reminder import Reminder, ReminderType
from app.models.user import User
from app.services.provider_notices import Notice, apply_notices


def add_title(db, title, tvdb_id, content_type="tv_show"):
    row = Content(title=title, content_type=content_type)
    db.add(row)
    db.flush()
    db.add(ContentExternalId(provider="tvdb", kind=content_type, external_id=str(tvdb_id), content_id=row.id))
    db.flush()
    return row


def add_user(db, name="u1"):
    user = User(username=name, email=f"{name}@example.com")
    db.add(user)
    db.flush()
    return user


def delete_notice(tvdb_id, content_type="tv_show"):
    return Notice(action="delete", provider="tvdb", content_type=content_type, external_id=str(tvdb_id))


def merge_notice(old_id, new_id, content_type="tv_show"):
    return Notice(
        action="merge", provider="tvdb", content_type=content_type, external_id=str(old_id), merged_into=str(new_id)
    )


def test_delete_removes_a_title_nobody_has_in_a_library(db_session):
    dead = add_title(db_session, "Dead Show", 100)
    dead_id = dead.id

    result = apply_notices(db_session, [delete_notice(100)])

    assert result == {"deleted": 1, "flagged": 0, "merged": 0, "ignored": 0}
    assert db_session.get(Content, dead_id) is None
    assert db_session.query(ContentExternalId).filter_by(external_id="100").count() == 0


def test_delete_keeps_a_title_that_is_in_a_library_and_stops_refreshing_it(db_session):
    kept = add_title(db_session, "Loved Show", 101)
    user = add_user(db_session)
    item = LibraryItem(user_id=user.id, content_id=kept.id, status=WatchStatus.WATCHING)
    db_session.add(item)
    db_session.flush()

    result = apply_notices(db_session, [delete_notice(101)])

    assert result == {"deleted": 0, "flagged": 1, "merged": 0, "ignored": 0}
    db_session.refresh(kept)
    assert db_session.get(LibraryItem, item.id).content_id == kept.id
    assert kept.next_refresh_at is None
    assert "deleted" in kept.last_error
    assert db_session.query(ContentExternalId).filter_by(external_id="101").count() == 0


def test_merge_gives_the_survivor_the_ids_it_lacked_going_by_the_external_id_table(db_session):
    from tests.id_helpers import add_title as add_table_only_title

    add_table_only_title(db_session, "Old Entry", "tv_show", ids={"tvdb": 300, "imdb": "tt9"})
    survivor = add_table_only_title(db_session, "Survivor", "tv_show", ids={"tvdb": 301})

    apply_notices(db_session, [merge_notice(300, 301)])

    db_session.expire_all()
    ids = {(r.provider, r.external_id) for r in db_session.query(ContentExternalId).filter_by(content_id=survivor.id)}
    assert ids == {("tvdb", "300"), ("tvdb", "301"), ("imdb", "tt9")}


def test_merge_moves_the_id_to_the_surviving_title_and_library_items_follow(db_session):
    old = add_title(db_session, "Old Entry", 200)
    survivor = add_title(db_session, "Survivor", 201)
    old_id, survivor_id = old.id, survivor.id
    user = add_user(db_session)
    item = LibraryItem(user_id=user.id, content_id=old_id, status=WatchStatus.COMPLETED, rating=5)
    db_session.add(item)
    db_session.flush()

    result = apply_notices(db_session, [merge_notice(200, 201)])

    assert result == {"deleted": 0, "flagged": 0, "merged": 1, "ignored": 0}
    assert db_session.get(Content, old_id) is None
    moved = db_session.get(LibraryItem, item.id)
    assert (moved.content_id, moved.rating) == (survivor_id, 5)
    ids = {(r.external_id, r.content_id) for r in db_session.query(ContentExternalId).filter_by(provider="tvdb")}
    # the old id stays as an alias of the survivor so the provider's old id never recreates a duplicate
    assert ids == {("200", survivor_id), ("201", survivor_id)}


def test_merge_when_a_user_tracks_both_keeps_one_item_and_nothing_else_is_orphaned_or_conflicting(db_session):
    old = add_title(db_session, "Old Entry", 210)
    survivor = add_title(db_session, "Survivor", 211)
    old_id, survivor_id = old.id, survivor.id
    user, other = add_user(db_session, "a"), add_user(db_session, "b")
    old_item = LibraryItem(user_id=user.id, content_id=old_id, status=WatchStatus.WATCHING)
    kept_item = LibraryItem(user_id=user.id, content_id=survivor_id, status=WatchStatus.PLANNED)
    other_item = LibraryItem(user_id=other.id, content_id=old_id, status=WatchStatus.PLANNED)
    db_session.add_all([old_item, kept_item, other_item])
    db_session.flush()
    reminder = Reminder(
        user_id=user.id,
        library_item_id=old_item.id,
        content_id=old_id,
        reminder_type=ReminderType.NEXT_EPISODE,
        scheduled_time=datetime(2026, 11, 1, tzinfo=UTC),
    )
    db_session.add_all(
        [
            reminder,
            Episode(content_id=old_id, season_number=1, episode_number=1, title="dup"),
            Episode(content_id=old_id, season_number=1, episode_number=2, title="only on old"),
            Episode(content_id=survivor_id, season_number=1, episode_number=1, title="kept"),
            UserContentRank(user_id=user.id, content_id=old_id, rank_score=0.1),
            UserContentRank(user_id=user.id, content_id=survivor_id, rank_score=0.9),
            Gossip(title="Buzz", source_url="https://example.com/b", source_name="x", related_content_id=old_id),
        ]
    )
    db_session.flush()
    reminder_id, other_item_id, kept_item_id = reminder.id, other_item.id, kept_item.id

    apply_notices(db_session, [merge_notice(210, 211)])
    db_session.expire_all()

    assert db_session.get(LibraryItem, other_item_id).content_id == survivor_id
    assert db_session.query(LibraryItem).filter_by(user_id=user.id).count() == 1
    moved_reminder = db_session.get(Reminder, reminder_id)
    assert (moved_reminder.library_item_id, moved_reminder.content_id) == (kept_item_id, survivor_id)
    episodes = {(e.episode_number, e.title) for e in db_session.query(Episode).filter_by(content_id=survivor_id)}
    assert episodes == {(1, "kept"), (2, "only on old")}
    ranks = db_session.query(UserContentRank).filter_by(content_id=survivor_id).all()
    assert [r.rank_score for r in ranks] == [0.9]
    assert db_session.query(Gossip).one().related_content_id == survivor_id


def test_merge_into_an_id_we_do_not_have_gives_the_title_the_new_id(db_session):
    title = add_title(db_session, "Renumbered", 220)
    title_id = title.id

    result = apply_notices(db_session, [merge_notice(220, 221)])

    assert result["merged"] == 1
    db_session.refresh(title)
    rows = db_session.query(ContentExternalId).filter_by(provider="tvdb", content_id=title_id).all()
    assert [r.external_id for r in rows] == ["221"]


def test_unknown_ids_and_replayed_notices_change_nothing(db_session):
    add_title(db_session, "Survivor", 231)
    add_title(db_session, "Old", 230)
    notices = [merge_notice(230, 231), delete_notice(999)]

    first = apply_notices(db_session, notices)
    second = apply_notices(db_session, notices)

    assert first == {"deleted": 0, "flagged": 0, "merged": 1, "ignored": 1}
    assert second == {"deleted": 0, "flagged": 0, "merged": 0, "ignored": 2}


def test_every_applied_notice_is_logged(db_session, caplog):
    add_title(db_session, "Gone", 240)
    add_title(db_session, "Old", 241)
    add_title(db_session, "Survivor", 242)

    with caplog.at_level(logging.INFO, logger="app.services.provider_notices"):
        apply_notices(db_session, [delete_notice(240), merge_notice(241, 242)])

    applied = [r.getMessage() for r in caplog.records if "notice applied" in r.getMessage()]
    assert len(applied) == 2
    assert "240" in applied[0] and "241" in applied[1] and "242" in applied[1]
