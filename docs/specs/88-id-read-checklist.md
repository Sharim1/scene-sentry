# #88 checklist: reads of provider ids moved to `content_external_id`

Parent spec #67, design ADR-0006. The old id columns on `content` stay (dropped in #89).
A batch is done when nothing in it reads `content.tmdb_id / imdb_id / tvdb_id / tvmaze_id / isbn`
and the full test suite passes.

- [x] 1. TVDB updates feed: queue known titles by id (`app/services/tvdb_updates.py`)
- [x] 2. Enrichment/refresh: which provider id to ask for each title (`ContentDiscoveryService._external_id_for`, via new `ContentRepository.external_ids_for`)
