"""Follow TVDB's updates feed instead of re-crawling (ADR-0006).

Each run asks the feed what changed since a stored bookmark (minus an overlap, so updates
stamped right at the boundary are not lost) and queues only the titles we already know for
refresh. The bookmark moves only after a successful run. If the bookmark is older than the
feed's window, the feed cannot tell us everything that changed, so the tier planner covers
the gap instead.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.content import Content
from app.models.external_id import ContentExternalId
from app.models.sync_state import SyncState
from app.services.provider_notices import Notice, apply_notices

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class UpdatesSync:
    """Follows one provider's updates feed per stream. Subclasses name the provider, its streams and
    (through ``<provider>_updates_*`` settings) its window and overlap."""

    provider_name: str
    streams: tuple[str, ...]

    def __init__(self, db: Session, provider: Any) -> None:
        self.db = db
        self.provider = provider

    @property
    def window_days(self) -> int:
        return int(getattr(settings, f"{self.provider_name}_updates_window_days"))

    @property
    def overlap_minutes(self) -> int:
        return int(getattr(settings, f"{self.provider_name}_updates_overlap_minutes"))

    def _utc_now(self) -> datetime:
        return utc_now()

    def run(self) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for stream in self.streams:
            results[stream] = self._sync_stream(stream)
            if results[stream]["status"] == "timeout":
                break  # out of time: the other streams wait for the next run
        return results

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
            failed_notices = applied.failed
        except SoftTimeLimitExceeded:
            return self._record_failure(stream, started, "timeout", "soft time limit exceeded")
        except Exception as exc:
            return self._record_failure(stream, started, "failed", f"{type(exc).__name__}: {exc}")

        state = self._get_state(stream)
        state.watermark, state.status = started, "ok"
        state.last_error = f"{failed_notices} notice(s) failed and were skipped" if failed_notices else None
        self.db.commit()
        return {"status": "ok", "queued": queued}

    def _record_failure(self, stream: str, started: datetime, status: str, error: str) -> dict:
        """Roll back the unfinished run; the bookmark stays, so the next run repeats it."""
        self.db.rollback()
        state = self._get_state(stream)
        state.status = status
        state.last_error = error[:2000]
        state.last_run_at = started
        self.db.commit()
        logger.warning("%s/%s updates %s, bookmark unchanged: %s", self.provider_name, stream, status, error)
        return {"status": status, "queued": 0}

    def _read_updates(self, stream: str, since: datetime) -> tuple[list[int], list[Notice]]:
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
            content_ids = select(ContentExternalId.content_id).where(
                ContentExternalId.provider == self.provider_name,
                ContentExternalId.kind == stream,
                ContentExternalId.external_id.in_([str(i) for i in chunk]),
            )
            queued += (
                self.db.query(Content)
                .filter(Content.id.in_(content_ids))
                .update({Content.next_refresh_at: now}, synchronize_session=False)
            )
        return queued


class TVDBUpdatesSync(UpdatesSync):
    provider_name = "tvdb"
    streams = ("tv_show", "movie")
