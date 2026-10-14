"""Follow TVmaze's updates feed the same way as TVDB's (ADR-0006), sharing its machinery.

Same per-stream bookmark in ``sync_state``; only shows exist on TVmaze.
"""

from app.services.tvdb_updates import UpdatesSync


class TVMazeUpdatesSync(UpdatesSync):
    provider_name = "tvmaze"
    streams = ("tv_show",)
