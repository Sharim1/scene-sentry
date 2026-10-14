"""Re-check of catalog streams marked ``fully_synced`` (ADR-0006, issue #75).

Before the walker stopped treating a failed or filtered page as "end of catalog", a
stream could be marked fully synced too early. ``recheck_streams`` is read-only against
the database: for each fully synced stream it asks the provider for the pages just past
the saved cursor and says whether the end is genuine. ``reset_wrong_streams`` clears the
flag only on streams that this fresh check still calls wrong, so a genuine end can never
be reset by mistake. The cursor is kept; the fixed walker resumes from it.

Verdicts:
    genuine        the source has nothing past the cursor.
    wrong          the source still has pages or titles past the cursor.
    empty_catalog  nothing was ever fetched and the provider lists nothing (no browse
                   support, e.g. OMDb). The flag is meaningless but there is nothing to fill.
    unknown        the provider failed or is not active; no conclusion.

Note: a source that appended new titles since the last sync also reads as "wrong". That
is harmless, since the walker would fetch them next anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.discovery_state import DiscoveryState
from app.services.providers.base import ProviderError, is_end_of_stream


@dataclass
class StreamVerdict:
    provider: str
    content_type: str
    last_page: int
    total_items_fetched: int
    verdict: str
    detail: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.content_type)


def _probe(provider, content_type: str, page: int):
    if content_type == "movie":
        return provider.discover_movies(page=page)
    return provider.discover_tv_shows(page=page)


def _judge(provider, state: DiscoveryState) -> tuple[str, str]:
    if provider is None:
        return "unknown", "provider is not active or configured"
    try:
        if state.total_items_fetched == 0 and state.last_page == 0:
            first = _probe(provider, state.content_type, 1)
            if is_end_of_stream(first):
                return "empty_catalog", "provider lists no titles for this stream"
        page = state.last_page + 1
        result = _probe(provider, state.content_type, page)
    except ProviderError as e:
        return "unknown", f"provider failed: {e}"
    if result:
        return "wrong", f"page {page} has {len(result)} title(s) past the saved cursor"
    if not is_end_of_stream(result):
        return "wrong", f"page {page} exists on the source (nothing usable after filtering)"
    return "genuine", f"page {page} is empty on the source"


def recheck_streams(
    db: Session,
    providers: list,
) -> list[StreamVerdict]:
    """Read-only verdict for every stream currently marked fully synced.

    Asks the provider for the one page just past the saved cursor (GET requests only).
    """
    by_name = {p.name: p for p in providers}
    states = (
        db.query(DiscoveryState)
        .filter(DiscoveryState.fully_synced.is_(True))
        .order_by(DiscoveryState.provider, DiscoveryState.content_type)
        .all()
    )
    out: list[StreamVerdict] = []
    for st in states:
        verdict, detail = _judge(by_name.get(st.provider), st)
        out.append(StreamVerdict(st.provider, st.content_type, st.last_page, st.total_items_fetched, verdict, detail))
    return out


def reset_wrong_streams(
    db: Session,
    providers: list,
    streams: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Clear ``fully_synced`` on the named (provider, content_type) streams that are still wrong.

    Streams whose fresh verdict is anything but "wrong" are left untouched. Commits.
    Returns the streams actually reset. Raises ValueError for a name that is not a stream.
    """
    by_verdict = {v.key: v for v in recheck_streams(db, providers)}
    done: list[tuple[str, str]] = []
    for key in streams:
        exists = db.query(DiscoveryState).filter_by(provider=key[0], content_type=key[1]).first()
        if exists is None:
            raise ValueError(f"no discovery stream {key[0]}/{key[1]}")
        verdict = by_verdict.get(key)
        if verdict is None or verdict.verdict != "wrong":
            continue
        exists.fully_synced = False
        done.append(key)
    db.commit()
    return done


def format_report(verdicts: list[StreamVerdict]) -> str:
    if not verdicts:
        return "No streams are marked fully synced."
    lines = ["Streams marked fully synced:"]
    for v in verdicts:
        lines.append(
            f"  {v.provider}/{v.content_type}: {v.verdict.upper()} "
            f"(cursor page {v.last_page}, {v.total_items_fetched} items) - {v.detail}"
        )
    return "\n".join(lines)
