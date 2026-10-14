"""Identity resolver: decides whether an incoming title is an existing one, a new one, or a conflict.

Pure: plain facts in, a decision out, no database or network. Provider ids are tried
first, each kind kept apart (a TMDb 5 is not a TVDB 5) and scoped to the content type,
except IMDb ids which are global. Title, year and type are the fallback.
See docs/adr/0006-catalog-sync-architecture.md.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.providers.base import _normalise_title

ID_KINDS = ("imdb", "tmdb", "tvdb", "tvmaze")
_GLOBAL_KINDS = frozenset({"imdb"})  # one IMDb id names one title whatever its type (also in stored ids)
# Which id kind each provider's detail and episode calls take (OMDb is looked up by IMDb id).
PROVIDER_ID_KIND = {"tvmaze": "tvmaze", "tvdb": "tvdb", "omdb": "imdb"}


def item_ids(item: Any) -> dict[str, str]:
    """The provider ids an item (anything with ``imdb_id``, ``tmdb_id``... attributes) carries, as text."""
    return {kind: str(value) for kind in ID_KINDS if (value := getattr(item, f"{kind}_id", None))}


@dataclass(frozen=True, eq=False)
class Identity:
    """The facts about a title that matter for identity."""

    title: str
    content_type: str
    year: int | None = None
    ids: Mapping[str, Any] = field(default_factory=dict)
    ref: Any = None  # caller's handle for the thing these facts describe (row, item, ...)


@dataclass(frozen=True)
class Match:
    candidate: Identity


@dataclass(frozen=True)
class Create:
    pass


@dataclass(frozen=True)
class Conflict:
    """Facts that disagree; the caller decides, the resolver does not guess."""

    candidates: tuple[Identity, ...]


Decision = Match | Create | Conflict


def id_keys(i: Identity) -> list[tuple[Any, ...]]:
    keys: list[tuple[Any, ...]] = []
    for kind in ID_KINDS:
        value = i.ids.get(kind)
        if value:
            keys.append((kind, value) if kind in _GLOBAL_KINDS else (i.content_type, kind, value))
    return keys


def ids_disagree(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """True if both carry the same kind of id with different values."""
    return any(a.get(k) and b.get(k) and a[k] != b[k] for k in ID_KINDS)


def resolve(incoming: Identity, candidates: Sequence[Identity]) -> Decision:
    """Decide what ``incoming`` is, given the known ``candidates`` (earlier ones win ties)."""
    keys = set(id_keys(incoming))
    by_id: list[Identity] = []
    for c in candidates:
        if keys & set(id_keys(c)) and not any(c is seen for seen in by_id):
            by_id.append(c)
    if by_id:
        if len(by_id) > 1 or ids_disagree(incoming.ids, by_id[0].ids):
            return Conflict(tuple(by_id))
        return Match(by_id[0])

    title = _normalise_title(incoming.title)
    if not title:
        return Create()
    for c in candidates:
        if c.content_type != incoming.content_type or _normalise_title(c.title) != title:
            continue
        if incoming.year and c.year != incoming.year:
            continue
        if not ids_disagree(incoming.ids, c.ids):
            return Match(c)
    return Create()
