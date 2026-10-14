# #88 checklist: reads of provider ids moved to `content_external_id`

Parent spec #67, design ADR-0006. The old id columns on `content` stay (dropped in #89).
A batch is done when nothing in it reads `content.tmdb_id / imdb_id / tvdb_id / tvmaze_id / isbn`
and the full test suite passes. Tests put ids only in the external-id table (`tests/id_helpers.py`),
so they pass only if the code reads the table.

- [x] 1. TVDB updates feed: queue known titles by id (`app/services/tvdb_updates.py`)
- [x] 2. Enrichment/refresh: which provider id to ask for each title (`ContentDiscoveryService._external_id_for`, via new `ContentRepository.external_ids_for`)
- [x] 3. Title page: IMDb link (`app/routes/content.py`, `templates/content_detail.html`)
- [x] 4. Repository matching and merging: id-conflict checks, "fill a missing id", ids recorded after a merge or insert, TMDb dict upsert (`app/repositories/content_repo.py`)
- [ ] 5. Not moved on purpose: `app/services/catalog_audit.py` (`manage.py audit-ids`, issue #73). It is the pre-migration check for what would break the unique rule, so it must look at the old columns. Retire it with the columns in #89.

Still written (not read): the old columns are filled together with the table until #89 drops them.
Out of scope: `episode.tvmaze_id / tvdb_id / imdb_id` (episodes keep their own ids; no external-id table for them).
