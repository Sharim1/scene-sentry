# #88 checklist: reads of provider ids moved to `content_external_id`

Parent spec #67, design ADR-0006. The old id columns on `content` were dropped in #89 (migration `a1b6c4d8e2f7`).
A batch is done when nothing in it reads `content.tmdb_id / imdb_id / tvdb_id / tvmaze_id / isbn`
and the full test suite passes. Tests put ids only in the external-id table (`tests/id_helpers.py`),
so they pass only if the code reads the table.

- [x] 1. TVDB updates feed: queue known titles by id (`app/services/tvdb_updates.py`)
- [x] 2. Enrichment/refresh: which provider id to ask for each title (`ContentDiscoveryService._external_id_for`, via new `ContentRepository.external_ids_for`)
- [x] 3. Title page: IMDb link (`app/routes/content.py`, `templates/content_detail.html`)
- [x] 4. Repository matching and merging: id-conflict checks, "fill a missing id", ids recorded after a merge or insert, TMDb dict upsert (`app/repositories/content_repo.py`)
- [x] 5. Conflict screening against stored titles, added by #85 (`ContentDiscoveryService._screen_stored`); TVDB and TVmaze feeds share one table query (`provider_name`)
- [x] 6. Provider delete and merge notices, added by #87 (`app/services/provider_notices.py`)
- [x] 7. `app/services/catalog_audit.py` (`manage.py audit-ids`, issue #73), done in #89: rewritten to read `content_external_id`. The duplicate-id check is gone (the table's primary key makes it impossible); the movie/show shared-id and likely-duplicate checks remain.

The dual writes to the old columns were removed in #89.
Out of scope: `episode.tvmaze_id / tvdb_id / imdb_id` (episodes keep their own ids; no external-id table for them).
