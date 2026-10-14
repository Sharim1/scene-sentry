"""Follow TVDB's updates feed instead of re-crawling (ADR-0006).

Each run asks the feed what changed since a stored bookmark (minus an overlap, so updates
stamped right at the boundary are not lost) and queues only the titles we already know for
refresh. The bookmark moves only after a successful run. If the bookmark is older than the
feed's window, the feed cannot tell us everything that changed, so the tier planner covers
the gap instead.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models.content import Content
from app.models.sync_state import SyncState
from app.services.provider_notices import apply_notices

logger = logging.getLogger(__name__)

PROVIDER = "tvdb"
STREAMS = ("tv_show", "movie")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class TVDBUpdatesSync:
    """Follows one provider's updates feed per stream. Subclasses name the provider and its knobs."""

    provider_name = PROVIDER
    streams = STREAMS
    id_attr = "tvdb_id"

    def __init__(self, db: Session, provider):
        self.db = db
        self.provider = provider

    @property
    def window_days(self) -> int:
        return settings.tvdb_updates_window_days

    @property
    def overlap_minutes(self) -> int:
        return settings.tvdb_updates_overlap_minutes

    def _utc_now(self) -> datetime:
        return utc_now()

    def run(self) -> dict[str, dict]:
        return {stream: self._sync_stream(stream) for stream in self.streams}

    def _get_state(self, stream: str) -> SyncState:
        state = self.db.query(SyncState).filter_by(provider=self.provider_name, stream=stream).first()
        if not state:
            state = SyncState(provider=self.provider_name, stream=stream)
            self.db.add(state)
            self.db.flush()
        return state

    def _sync_stream(self, stream: str) -> dict:
        started = self._utc_now()
        state = self._get_state(stream)
        state.last_run_at = started

        if state.watermark is None:
            # Nothing to follow yet: start the bookmark now; the planner handles existing titles.
            state.watermark, state.status, state.last_error = started, "ok", None
            self.db.commit()
            return {"status": "ok", "queued": 0}

        watermark = _aware(state.watermark)
        if started - watermark > timedelta(days=self.window_days):
            state.watermark, state.status, state.last_error = started, "gap_fallback", None
            self.db.commit()
            logger.warning(
                "%s/%s bookmark older than the feed window; tier planner covers the gap", self.provider_name, stream
            )
            return {"status": "gap_fallback", "queued": 0}

        since = watermark - timedelta(minutes=self.overlap_minutes)
        try:
            ids, notices = self._read_updates(stream, since)
            applied = apply_notices(self.db, notices)
            queued = self._queue_known(stream, ids, started)
            if notices:
                logger.info("%s/%s notices applied: %s", self.provider_name, stream, applied)
        except Exception as exc:
            self.db.rollback()
            state = self._get_state(stream)
            state.status = "failed"
            state.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            state.last_run_at = started
            self.db.commit()
            logger.warning("%s/%s updates failed, bookmark unchanged: %s", self.provider_name, stream, exc)
            return {"status": "failed", "queued": 0}

        state = self._get_state(stream)
        state.watermark, state.status, state.last_error = started, "ok", None
        self.db.commit()
        return {"status": "ok", "queued": queued}

    def _read_updates(self, stream: str, since: datetime):
        """(changed ids, delete/merge notices). Providers whose feed has no notices only list ids."""
        read = getattr(self.provider, "read_updates", None)
        if read is None:
            return self.provider.get_updated_ids(stream, since), []
        return read(stream, since)

    def _queue_known(self, stream: str, ids: list[int], now: datetime) -> int:
        queued = 0
        ids = list(set(ids))
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            queued += (
                self.db.query(Content)
                .filter(Content.content_type == stream, getattr(Content, self.id_attr).in_(chunk))
                .update({Content.next_refresh_at: now}, synchronize_session=False)
            )
        return queued
