"""Follow TVmaze's updates feed the same way as TVDB's (ADR-0006), sharing its machinery.

Same per-stream bookmark in ``sync_state``; only shows exist on TVmaze.
"""

from datetime import datetime

from app.config import settings
from app.services.tvdb_updates import TVDBUpdatesSync, utc_now


class TVMazeUpdatesSync(TVDBUpdatesSync):
    provider_name = "tvmaze"
    streams = ("tv_show",)
    id_attr = "tvmaze_id"

    @property
    def window_days(self) -> int:
        return settings.tvmaze_updates_window_days

    @property
    def overlap_minutes(self) -> int:
        return settings.tvmaze_updates_overlap_minutes

    def _utc_now(self) -> datetime:
        return utc_now()
