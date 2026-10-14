"""Apply a provider's delete and merge notices to our titles and external ids (ADR-0006).

A notice says an id was deleted at the provider, or merged into another id. Deleted ids leave
the external-id table; a title nobody has in a library goes with them, one that is in a library
is kept (and stops being refreshed) so no user loses an item. A merge moves the id to the
surviving title and re-points everything that referenced the old title. Every applied notice is
logged. Rows are changed with flush only; the caller commits.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.content import Content
from app.models.episode import Episode
from app.models.external_id import ContentExternalId
from app.models.gossip import Gossip
from app.models.library import LibraryItem
from app.models.ranking import UserContentRank
from app.models.reminder import Reminder
from app.repositories.content_repo import ContentRepository
from app.services.identity import ID_KINDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notice:
    """One provider notice. ``merged_into`` is the surviving id, set only for a merge."""

    action: str  # "delete" | "merge"
    provider: str
    content_type: str
    external_id: str
    merged_into: str | None = None


def apply_notices(db: Session, notices: list[Notice]) -> dict[str, int]:
    result = {"deleted": 0, "flagged": 0, "merged": 0, "ignored": 0}
    for notice in notices:
        title = _find(db, notice.provider, notice.content_type, notice.external_id)
        if title is None:
            result["ignored"] += 1
            logger.info("notice ignored, id not in catalog: %s", notice)
            continue
        if notice.action == "merge" and notice.merged_into:
            outcome = _apply_merge(db, notice, title)
        else:
            outcome = _apply_delete(db, notice, title)
        result[outcome] += 1
    return result


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
        if notice.provider in ID_KINDS:
            setattr(source, f"{notice.provider}_id", int(notice.merged_into))
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
    db.query(Gossip).filter_by(related_content_id=sid).update(
        {Gossip.related_content_id: tid}, synchronize_session=False
    )
    db.query(Content).filter_by(adapted_from_id=sid).update({Content.adapted_from_id: tid}, synchronize_session=False)
    db.flush()
    db.expire(source)
    db.delete(source)
    db.flush()


def _ids_of(db: Session, titles: list[Content]) -> list[tuple[Content, dict[str, str]]]:
    """Each title with its ids ({provider: external id}) from the external-id table."""
    found = ContentRepository(db).external_ids_for([t.id for t in titles])
    return [(t, found[t.id]) for t in titles]


def _flag_deleted(title: Content, notice: Notice) -> None:
    """Keep the title for the users who track it; the dead id is dropped and refresh stops."""
    title.next_refresh_at = None
    title.last_error = f"deleted by {notice.provider} (id {notice.external_id})"


def _remove_title(db: Session, title: Content) -> None:
    """Delete a title and the rows that only exist because of it."""
    for model in (Episode, UserContentRank, Reminder):
        db.query(model).filter_by(content_id=title.id).delete(synchronize_session=False)
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
