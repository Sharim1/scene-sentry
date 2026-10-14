"""The review list: titles the resolver reported as a conflict, parked with the reason.

See docs/adr/0006-catalog-sync-architecture.md and issue #83.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.models.review_item import ReviewItem
from app.services.identity import ID_KINDS, Conflict, Identity
from app.services.providers.base import _normalise_title


def _describe(i: Identity) -> str:
    ids = ", ".join(f"{k} {i.ids[k]}" for k in ID_KINDS if i.ids.get(k))
    return f"{i.title!r} ({ids})" if ids else repr(i.title)


def reason_for(incoming: Identity, conflict: Conflict) -> str:
    others = "; ".join(_describe(c) for c in conflict.candidates)
    if len(conflict.candidates) > 1:
        return f"Its ids point at {len(conflict.candidates)} different titles: {others}"
    return f"Its ids disagree with an existing title: {others}"


def fingerprint(i: Identity) -> str:
    facts = [i.content_type, _normalise_title(i.title), i.year, {k: str(i.ids[k]) for k in ID_KINDS if i.ids.get(k)}]
    return hashlib.sha1(json.dumps(facts, sort_keys=True).encode()).hexdigest()  # noqa: S324 - not security


def park(db: Session, incoming: Identity, conflict: Conflict) -> None:
    """Add the conflicting title to the review list unless it is already there (caller commits)."""
    key = fingerprint(incoming)
    if db.query(ReviewItem.id).filter_by(fingerprint=key).first():
        return
    db.add(
        ReviewItem(
            fingerprint=key,
            title=incoming.title[:200],
            content_type=incoming.content_type,
            provider=getattr(incoming.ref, "provider", None),
            reason=reason_for(incoming, conflict),
        )
    )


def list_review(db: Session) -> list[ReviewItem]:
    """Everything waiting for review, oldest first."""
    return db.query(ReviewItem).order_by(ReviewItem.id).all()


def format_review(entries: list[ReviewItem]) -> str:
    """Plain-text rendering of the list, for the CLI."""
    if not entries:
        return "Nothing waiting for review."
    noun = "title" if len(entries) == 1 else "titles"
    lines = [f"{len(entries)} {noun} waiting for review:"]
    for e in entries:
        lines.append(f"  #{e.id} [{e.content_type}] {e.title} (from {e.provider or 'unknown'})")
        lines.append(f"      {e.reason}")
    return "\n".join(lines)
