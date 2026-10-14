"""Apply a provider's delete and merge notices to our titles and external ids (ADR-0006).

A notice says an id was deleted at the provider, or merged into another id. Deleted ids leave
the external-id table; a title nobody has in a library goes with them, one that is in a library
is kept (and stops being refreshed) so no user loses an item. A merge moves the id to the
surviving title and re-points everything that referenced the old title. Every applied notice is
logged. Rows are changed with flush only; the caller commits.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Column, Integer, MetaData, Table, delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.content import Content
from app.models.episode import Episode
from app.models.external_id import ContentExternalId
from app.models.gossip import Gossip
from app.models.library import LibraryItem
from app.models.ranking import UserContentRank
from app.models.reminder import Reminder

logger = logging.getLogger(__name__)

# The recommendations model is not registered with the app (its relationships have no other side), but
# the table has a non-null foreign key to content, so a notice must still move or drop its rows.
_RECOMMENDATIONS = Table("recommendations", MetaData(), Column("content_id", Integer))


class NoticeAction(StrEnum):
    DELETE = "delete"
    MERGE = "merge"


@dataclass(frozen=True)
class Notice:
    """One provider notice. ``merged_into`` is the surviving id, set only for a merge."""

    action: NoticeAction
    provider: str
    content_type: str
    external_id: str
    merged_into: str | None = None


@dataclass
class NoticeResult:
    """How many notices ended each way. A ``failed`` notice is skipped so it cannot block the rest."""

    deleted: int = 0
    flagged: int = 0
    merged: int = 0
    ignored: int = 0
    failed: int = 0


def apply_notices(db: Session, notices: list[Notice]) -> NoticeResult:
    result = NoticeResult()
    for notice in notices:
        try:
            with db.begin_nested():
                outcome = _apply_one(db, notice)
        except Exception:
            outcome = "failed"
            logger.exception("notice failed and was skipped: %s", notice)
        setattr(result, outcome, getattr(result, outcome) + 1)
    return result


def _apply_one(db: Session, notice: Notice) -> str:
    title = _find(db, notice.provider, notice.content_type, notice.external_id)
    if title is None:
        logger.info("notice ignored, id not in catalog: %s", notice)
        return "ignored"
    if notice.action == NoticeAction.MERGE and notice.merged_into:
        return _apply_merge(db, notice, title)
    return _apply_delete(db, notice, title)


def _repoint_recommendations(db: Session, source_id: int, target_id: int | None) -> None:
    """Move (or with no target, drop) the recommendation rows of a title; absent table is fine."""
    statement = (
        delete(_RECOMMENDATIONS).where(_RECOMMENDATIONS.c.content_id == source_id)
        if target_id is None
        else update(_RECOMMENDATIONS).where(_RECOMMENDATIONS.c.content_id == source_id).values(content_id=target_id)
    )
    try:
        with db.begin_nested():
            db.execute(statement)
    except DBAPIError as e:
        logger.debug("recommendations not updated: %s", e)


def _apply_delete(db: Session, notice: Notice, title: Content) -> str:
    db.query(ContentExternalId).filter_by(
        provider=notice.provider, kind=notice.content_type, external_id=notice.external_id
    ).delete(synchronize_session=False)
    if db.query(LibraryItem).filter_by(content_id=title.id).count():
        _flag_deleted(title, notice)
        db.flush()
        logger.info("notice applied, title %s kept (in a library) and flagged: %s", title.id, notice)
        return "flagged"
    _remove_title(db, title)
    logger.info("notice applied, title %s deleted: %s", title.id, notice)
    return "deleted"


def _apply_merge(db: Session, notice: Notice, source: Content) -> str:
    target = _find(db, notice.provider, notice.content_type, notice.merged_into)
    if target is None:
        # The surviving id is not ours yet: the title simply carries the new id from now on.
        db.query(ContentExternalId).filter_by(
            provider=notice.provider, kind=notice.content_type, external_id=notice.external_id
        ).update({ContentExternalId.external_id: notice.merged_into}, synchronize_session=False)
        db.flush()
        logger.info("notice applied, title %s now carries id %s: %s", source.id, notice.merged_into, notice)
        return "merged"
    if target.id == source.id:
        logger.info("notice ignored, ids already on one title: %s", notice)
        return "ignored"
    _merge_titles(db, source, target)
    logger.info("notice applied, title %s merged into title %s: %s", source.id, target.id, notice)
    return "merged"


def _merge_titles(db: Session, source: Content, target: Content) -> None:
    """Move everything that points at ``source`` to ``target``, then remove ``source``.

    The old ids stay in the external-id table pointing at the survivor, so anything the provider
    still sends under an old id lands on the survivor instead of recreating the duplicate.
    """
    sid, tid = source.id, target.id
    db.query(ContentExternalId).filter_by(content_id=sid).update(
        {ContentExternalId.content_id: tid}, synchronize_session=False
    )

    # A user who tracks both keeps the survivor's item; the other item's reminders move over.
    survivor_items = {i.user_id: i.id for i in db.query(LibraryItem).filter_by(content_id=tid)}
    for item in db.query(LibraryItem).filter_by(content_id=sid).all():
        if item.user_id in survivor_items:
            db.query(Reminder).filter_by(library_item_id=item.id).update(
                {Reminder.library_item_id: survivor_items[item.user_id]}, synchronize_session=False
            )
            db.delete(item)
        else:
            item.content_id = tid
    db.flush()

    ranked = {r.user_id for r in db.query(UserContentRank).filter_by(content_id=tid)}
    for rank in db.query(UserContentRank).filter_by(content_id=sid).all():
        if rank.user_id in ranked:
            db.delete(rank)
        else:
            rank.content_id = tid
    have = {(e.season_number, e.episode_number) for e in db.query(Episode).filter_by(content_id=tid)}
    for episode in db.query(Episode).filter_by(content_id=sid).all():
        if (episode.season_number, episode.episode_number) in have:
            db.delete(episode)
        else:
            episode.content_id = tid
    db.query(Reminder).filter_by(content_id=sid).update({Reminder.content_id: tid}, synchronize_session=False)
    _repoint_recommendations(db, sid, tid)
    db.query(Gossip).filter_by(related_content_id=sid).update(
        {Gossip.related_content_id: tid}, synchronize_session=False
    )
    db.query(Content).filter_by(adapted_from_id=sid).update({Content.adapted_from_id: tid}, synchronize_session=False)
    db.flush()
    db.expire(source)
    db.delete(source)
    db.flush()


def _flag_deleted(title: Content, notice: Notice) -> None:
    """Keep the title for the users who track it; the dead id is dropped and refresh stops."""
    title.next_refresh_at = None
    title.last_error = f"deleted by {notice.provider} (id {notice.external_id})"


def _remove_title(db: Session, title: Content) -> None:
    """Delete a title and the rows that only exist because of it."""
    for model in (Episode, UserContentRank, Reminder):
        db.query(model).filter_by(content_id=title.id).delete(synchronize_session=False)
    _repoint_recommendations(db, title.id, None)
    db.query(Gossip).filter_by(related_content_id=title.id).update(
        {Gossip.related_content_id: None}, synchronize_session=False
    )
    db.query(ContentExternalId).filter_by(content_id=title.id).delete(synchronize_session=False)
    db.expire(title)
    db.delete(title)
    db.flush()


def _find(db: Session, provider: str, kind: str, external_id: str) -> Content | None:
    return (
        db.query(Content)
        .join(ContentExternalId, ContentExternalId.content_id == Content.id)
        .filter(
            ContentExternalId.provider == provider,
            ContentExternalId.kind == kind,
            ContentExternalId.external_id == external_id,
        )
        .first()
    )
