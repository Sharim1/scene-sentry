# How other apps build, sync and refresh a movie/TV catalog, and what Scene Sentry should do

Research date: 2026-10-12. Scope: read-only research against primary sources (real source code, official docs, specs). Nothing in the app was changed.

How to read the evidence marks:

- A URL with a commit hash (for example `.../blob/59c22e8.../File.cs#L28-L68`) points at code I cloned and read on this date. The hash pins the exact version, so the link will not drift.
- "UNVERIFIED" means I could not confirm it from a primary source. It is listed again in section 7.
- "Inference" means it is my reasoning from verified facts, not a quote from a source.

---

## 1. Short answer

1. Nobody serious re-crawls the whole catalog on a timer. They ask the provider "what changed since my last visit?" (TMDb `/changes`, TVmaze `/updates/shows`, TVDB `/updates`, Trakt `/updates/{date}`) and remember a timestamp ("watermark"), then fetch only those titles. Radarr does exactly this in code.
2. When a change feed is not available, they use refresh tiers: ongoing shows are refreshed often, finished shows rarely. Sonarr's rule is 6 hours for running shows and about 30 days for ended ones. Radarr uses 12 hours and 180 days.
3. The first big load comes from a bulk file (TMDb daily ID export, IMDb datasets, Wikidata dump), not from thousands of API calls.
4. Work is a pipeline with separate steps: fetch from the provider, clean it into one shape, find out which of our titles it is (identity), save in batches, then enrich. Plex even splits "match" and "get metadata" into two separate calls.
5. One title has many provider ids (TMDb, TVDB, IMDb, TVmaze). The safe pattern is one row per id in an id table with a database `UNIQUE` rule, so the database refuses duplicates. Sonarr and Radarr both ended up adding unique constraints after they had duplicate titles.
6. Scheduled jobs are tiny and safe to repeat. They have a time limit, a "do not start if one is already running" lock, and fast jobs (reminders) never share a worker with slow jobs (enrichment).
7. Our code already does a few of these (a cursor per provider, batch writes for titles and episodes, a time budget). It misses the big ones.
8. The three biggest gaps that explain our pain: (a) a failed provider call looks the same as "end of catalog", (b) there is no per-title "last refreshed / next due" record, so the same rows get picked forever, (c) identity is only enforced in Python, never by the database.
9. Recommendation: keep Celery + Redis (no new infrastructure) and move step by step: first fix queue and failure handling, then add per-title refresh bookkeeping, then an `external_ids` table, then change feeds. Each step ships alone (section 6).
10. Do not adopt Kafka, Airflow, Kubernetes or a Postgres-based queue. The evidence does not justify them at our size, and the 270 ms database link makes a database queue worse, not better.

---

## 2. Projects studied

| # | Project | What it is | Primary sources read | Good model for us? |
|---|---|---|---|---|
| 1 | Sonarr (Servarr) | TV library manager, syncs series and episodes from TheTVDB through a metadata proxy ("SkyHook") | Cloned code, commit `59c22e8` | Yes, for refresh tiers, a persisted job queue with de-duplication, per-host rate limit, unique id constraints. Its metadata server is closed (not read). |
| 2 | Radarr (Servarr) | Same idea for movies, TMDb based | Cloned code, commit `b3396e2` | Yes, the best example of change feed plus watermark plus tier fallback |
| 3 | Jellyfin | Media server with pluggable metadata providers and scheduled tasks | Cloned code, commit `61f9a9d` | Partly: provider interface, ids dictionary, lock-field idea, "task already running" guard. Library scanning part does not apply. |
| 4 | Overseerr (Seerr) | Request manager that resolves everything to TMDb ids | Cloned code, commit `98ea135` | Partly: "recent" scan vs "full" scan, stored `lastScan` watermark with overlap, per-title lock |
| 5 | Trakt (open `trakt/trakt-api` repo, docs and API contracts only; the server is closed) | Large tracker; public API contract is the evidence | Cloned repo, commit `dadb51b` | Yes as a contract to learn from (updates endpoint, ids object, "summary endpoint is the source of truth"). Its policy forbids mirroring its catalog, so it is not a data source for us. |
| 6 | Yamtrack | Open-source tracker (Django, Celery, Redis, DB scheduler), the closest in kind to us | Cloned code, commit `5095564` | Yes for ops (concurrency 1, time limit, DB scheduler) and id uniqueness. No cross-provider merge, so not for identity. |
| 7 | MediaManager (maxdorninger) | Python/FastAPI/Postgres TV and movie manager with TMDb and TVDB | Cloned code, commit `98f2532` | Yes: same stack as us, tasks and cron schedules stored in Postgres, "refresh only non-ended shows" tier, a caching metadata relay |
| 8 | Plex custom metadata provider example (`plexinc/tmdb-example-provider`) | Official example of Plex's provider contract | Cloned repo, commit `3348a89` | Yes for the pattern "match" separate from "metadata", ids as `provider://id` |
| 9 | Provider docs: TMDb, TVDB v4, TVmaze, IMDb datasets, Wikidata | The feeds themselves | Official docs (section 8) | These decide what we can build |
| 10 | MediaWiki job queue | Famous background-job system | Official manual | Weak: only the idea of separate runners per job type |
| 11 | Netflix Media Database (NMDB) | Netflix tech blog | Search result excerpts only | No. It stores technical media-timeline data, not third-party catalog ingestion. Not used as a model. |
| 12 | Kodi scrapers | Searched, page returned 403 | none | UNVERIFIED, not used |

### 2.1 Sonarr

- Scheduled jobs are rows in a table with an interval, last-run time and a priority, not hidden timers. A 30-second timer asks which rows are due and pushes them onto a command queue. `ScheduledTask` has `TypeName, Interval, LastExecution, Priority, LastStartTime` ([ScheduledTask.cs](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Jobs/ScheduledTask.cs), [Scheduler.cs L30-L52](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Jobs/Scheduler.cs#L30-L52)). The "refresh series" job runs every 12 hours ([TaskManager.cs L108-L111](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Jobs/TaskManager.cs#L108-L111)).
- The queue refuses duplicates: before adding a command it checks "already queued or started with an equal body" and returns the existing one ([CommandQueueManager.cs L101-L125](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Messaging/Commands/CommandQueueManager.cs#L101-L125)). This is the "no overlapping runs" rule built into the queue itself.
- After a crash, commands left in "started" state are marked "orphaned" on startup, so nothing stays stuck forever ([CommandQueueManager.cs L276-L280](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Messaging/Commands/CommandQueueManager.cs#L276-L280), [CommandRepository.cs L32-L40](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Messaging/Commands/CommandRepository.cs#L32-L40)).
- The refresh job does not refresh everything. `ShouldRefreshSeries` decides per series: refresh if last sync is over 30 days old, or an aired episode still has the title "TBA"; skip if synced less than 6 hours ago; refresh if the show is not "Ended"; for ended shows refresh only if the last episode aired in the last 30 days ([ShouldRefreshSeries.cs L28-L68](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Tv/ShouldRefreshSeries.cs#L28-L68)). One bad series does not stop the loop: errors are caught per series and the result is marked "indeterminate" ([RefreshSeriesService.cs L218-L291](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Tv/RefreshSeriesService.cs#L218-L291)).
- Every outgoing HTTP request can carry a rate limit that is applied per host, in one place in the HTTP client, not inside each provider ([HttpClient.cs L148-L151](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Common/Http/HttpClient.cs#L148-L151)).
- Metadata does not come straight from TVDB. Sonarr calls its own proxy `https://skyhook.sonarr.tv/v2/tvdb/{route}/` ([SonarrCloudRequestBuilder.cs L18](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Common/Cloud/SonarrCloudRequestBuilder.cs#L18)). One caching proxy shields TheTVDB from every user. The proxy code is not in this repo (UNVERIFIED how it syncs from TVDB).
- Identity: `Series` has one id column per provider (`TvdbId, TvMazeId, ImdbId, TmdbId, ...`) ([Series.cs L26-L32](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Tv/Series.cs#L26-L32)), but `TvdbId` is the key and is `UNIQUE`. Migration 018 "remove_duplicates" and 019 "restore_unique_constraints" show they hit duplicates and fixed them with the database ([018](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Datastore/Migration/018_remove_duplicates.cs), [019 L12-L16](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Datastore/Migration/019_restore_unique_constraints.cs#L12-L16)).
- Lesson: ids as columns works when ONE provider is the declared key. They do not try to merge by title.

### 2.2 Radarr

- The refresh job asks the metadata server for "movies changed since the last start time" and refreshes only those. The watermark is the job's own `LastStartTime`. It is only trusted if it is less than 14 days old (matching TMDb's maximum window). Otherwise it falls back to the tier rule ([RefreshMovieService.cs L256-L282](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/Movies/RefreshMovieService.cs#L256-L282)).
- The call is `GET movie/changed?since=...`, with the start time moved back 15 minutes and rounded down to the hour "to ensure we cover gap" (overlap) ([SkyHookProxy.cs L55-L70](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/MetadataSource/SkyHook/SkyHookProxy.cs#L55-L70)).
- Tier fallback: refresh if the last sync is over 180 days old; never if under 12 hours; always while the movie is Announced or In Cinemas; and for Released only if the physical release was within 30 days ([ShouldRefreshMovie.cs L30-L55](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/Movies/ShouldRefreshMovie.cs#L30-L55)).
- Identity: migration 186 "fix_tmdb_duplicates" deletes duplicate TMDb rows and then makes `TmdbId` unique ([186](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/Datastore/Migration/186_fix_tmdb_duplicates.cs#L14-L19)). There is also a separate `MovieMetadata` table (provider data, with `LastInfoSync`) apart from the user's `Movie` ([MovieMetadata.cs](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/Movies/MovieMetadata.cs)). That is a "catalog vs. user data" split.

### 2.3 Jellyfin

- Every item has a plain dictionary of provider ids, `Dictionary<string,string> ProviderIds` ([IHasProviderIds.cs](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Model/Entities/IHasProviderIds.cs)). New providers add keys without a schema change. Ids are validated before use ([MetadataService.cs L293-L309](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Providers/Manager/MetadataService.cs#L293-L309)).
- Providers are plug-ins behind a narrow interface: `GetMetadata(info)` and `GetSearchResults(info)` per item type ([IRemoteMetadataProvider.cs](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Controller/Providers/IRemoteMetadataProvider.cs)). The merge of provider results into the item is a separate step (`MergeData`) honouring `LockedFields`, so a user's manual edit is not overwritten ([MetadataService.cs L585](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Providers/Manager/MetadataService.cs#L585)).
- Refresh modes are explicit: `None, ValidationOnly, Default, FullRefresh` ([MetadataRefreshMode.cs](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Controller/Providers/MetadataRefreshMode.cs)). There is a configurable "automatic refresh interval in days" per library ([MetadataService.cs L99](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Providers/Manager/MetadataService.cs#L99)).
- Scheduled tasks run with a cancellation token. A task can carry a maximum runtime (`CancelAfter`), and starting a task that is already running throws ([ScheduledTaskWorker.cs L306, L328](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/Emby.Server.Implementations/ScheduledTasks/ScheduledTaskWorker.cs#L300-L331)). Our `time_budget_seconds` is the same idea, but it is only applied to one of our tasks.

### 2.4 Overseerr

- Two scan jobs with two purposes: "recently added" (every few minutes, only items newer than the stored `lastScan`, minus a 10-minute safety buffer) and "full scan" (rare) ([plex/index.ts L84-L128](https://github.com/sct/overseerr/blob/98ea135f2d370faba0362d259fccf51d8fd44a16/server/lib/scanners/plex/index.ts#L84-L128)). This is the cheap-frequent plus expensive-rare split.
- The watermark is saved only after the run finishes, so a crashed run is simply repeated from the old mark.
- Work is done in bundles of 20 with a 4-second update rate ([baseScanner.ts L16-L17](https://github.com/sct/overseerr/blob/98ea135f2d370faba0362d259fccf51d8fd44a16/server/lib/scanners/baseScanner.ts#L16-L17)), and a per-title lock keyed by TMDb id so the same title is never processed twice at once ([baseScanner.ts L107](https://github.com/sct/overseerr/blob/98ea135f2d370faba0362d259fccf51d8fd44a16/server/lib/scanners/baseScanner.ts#L107)).
- Everything is resolved to one canonical id (TMDb) (`MediaIds { tmdbId, imdbId?, tvdbId? }`, [baseScanner.ts L24-L29](https://github.com/sct/overseerr/blob/98ea135f2d370faba0362d259fccf51d8fd44a16/server/lib/scanners/baseScanner.ts#L24-L29)).
- Not a model for: its jobs are in-process timers (`node-schedule`) on one machine.

### 2.5 Trakt (public contract in `trakt/trakt-api`)

- `GET /movies/updates/{start_date}` returns titles updated since a UTC date. The description says "We recommend storing the latest `updated_at` locally and using it for the next request." There is also an ids-only variant `/updates/id/{start_date}` ([contracts/movies/index.ts L433-L457](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/api/src/contracts/movies/index.ts#L433-L457)). This is the watermark pattern in the provider's own words.
- One title carries all its ids: `"ids": {"trakt":1,"slug":"batman-begins-2005","imdb":"tt0372784","tmdb":272}` ([standard-media-objects.md L14-L24](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/developer/src/lib/guides/standard-media-objects.md)).
- "Caching and Fresh Data": the summary endpoint is "the canonical source for current metadata". Titles embedded inside lists or sync responses are "a convenience snapshot for matching and display". Recommended client pattern: get ids from activity endpoints, then hydrate from the summary endpoint ([caching-and-fresh-data.md](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/developer/src/lib/guides/caching-and-fresh-data.md)). That is a "read model vs source of truth" rule.
- Rate limit: 500 GET calls per 5 minutes, with `Retry-After` on 429 ([rate-limiting.md](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/developer/src/lib/guides/rate-limiting.md)).
- Policy warning: "Scraping, bulk harvesting, or mirroring Trakt data to build a reusable copy of its catalog" is not permitted ([api-use-policy.md L28](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/developer/src/lib/guides/api-use-policy.md)). So Trakt should not be a catalog source for us.

### 2.6 Yamtrack

- Same stack family as ours: Django, Celery, Redis. Settings: `CELERY_WORKER_CONCURRENCY = 1`, `CELERY_WORKER_MAX_TASKS_PER_CHILD = 1`, `CELERY_TASK_TIME_LIMIT = 6 hours`, and `CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"` ([settings.py L545-L600](https://github.com/FuzzyGrim/Yamtrack/blob/5095564303dc873e5b6cc224941fbe068ddfddd7/src/config/settings.py#L545-L600)). One worker slot means there is no parallelism problem to reason about, and every task has a hard limit.
- The "reload calendar" refresh runs once a day; release notifications run every 10 minutes ([settings.py L576-L595](https://github.com/FuzzyGrim/Yamtrack/blob/5095564303dc873e5b6cc224941fbe068ddfddd7/src/config/settings.py#L576-L595)). It saves events with `bulk_create` and `bulk_update` ([events/calendar/main.py L56-L100](https://github.com/FuzzyGrim/Yamtrack/blob/5095564303dc873e5b6cc224941fbe068ddfddd7/src/events/calendar/main.py#L56-L100)).
- Identity is the pair `(source, media_id, media_type)` with database `UniqueConstraint`s ([app/models.py L86-L112](https://github.com/FuzzyGrim/Yamtrack/blob/5095564303dc873e5b6cc224941fbe068ddfddd7/src/app/models.py#L86-L112)). It never merges across providers, so a TMDb movie and the same movie from another source are two items. That avoids mis-merges but would not give us one title per film.
- It still has a single queue, so its release notifications could be delayed behind a long job. It avoids this only by keeping jobs short. Not evidence of a fix for starvation.

### 2.7 MediaManager

- Closest match to our stack: FastAPI + SQLAlchemy + Postgres, providers for TMDb and TVDB.
- Scheduler: `taskiq` with `PostgresqlBroker` and `PostgresqlSchedulerSource`, so queue and cron schedule live in Postgres. Startup schedules are seeded from a dict, for example `update_all_non_ended_shows_metadata_task` weekly (`"0 0 * * 1"`) and torrent import every 2 minutes ([scheduler.py](https://github.com/maxdorninger/MediaManager/blob/98f253238c780b462af42691154bf0d1f5723f92/media_manager/scheduler.py)).
- Tier: it refreshes "non-ended shows" only ([tv/metadata.py L141-L151](https://github.com/maxdorninger/MediaManager/blob/98f253238c780b462af42691154bf0d1f5723f92/media_manager/tv/metadata.py#L141-L151)).
- Identity: `UniqueConstraint("external_id", "metadata_provider")` on the show table ([tv/models.py L12](https://github.com/maxdorninger/MediaManager/blob/98f253238c780b462af42691154bf0d1f5723f92/media_manager/tv/models.py#L12)).
- Its `metadata_relay` is a small service in front of TMDb and TVDB, with the README advice to put a CDN or cache in front "as to not overload the TMDB/TVDB api" ([metadata_relay/README.md](https://github.com/maxdorninger/MediaManager/blob/98f253238c780b462af42691154bf0d1f5723f92/metadata_relay/README.md)). Same idea as SkyHook.
- Caution for us: a Postgres-based queue is fine when the database is next to the app. Ours is 270 ms away, so every poll and every lock would cost a slow round trip (inference).

### 2.8 Plex custom metadata provider example

- The provider contract has two separate features: **Match** ("find which item this is", input is a title, year or an external `guid` like `tvdb://152831`; `manual=1` returns ranked candidates) and **Metadata** (fetch the details for a known item) ([README.md](https://github.com/plexinc/tmdb-example-provider/blob/3348a89009bb418e083646fbe1360f544774bf71/README.md), [API Endpoints.md L107-L131](https://github.com/plexinc/tmdb-example-provider/blob/3348a89009bb418e083646fbe1360f544774bf71/docs/API%20Endpoints.md)).
- Ids come as a list of `provider://id` strings, for example `imdb://tt0088763`, `tmdb://105` ([Metadata.md L111-L117](https://github.com/plexinc/tmdb-example-provider/blob/3348a89009bb418e083646fbe1360f544774bf71/docs/Metadata.md)).
- Lesson: "identify" and "fetch" are different jobs with different inputs and different failure modes. Our `ContentProvider` mixes them (and `search`, `discover`, `get_upcoming`) in one fat interface.

### 2.9 What the providers themselves offer

| Provider | Change feed | Bulk file | Limits and terms | Source |
|---|---|---|---|---|
| TMDb | `GET /3/movie/changes` (and tv, person): 14 days max per call, 100 items per page, default last 24 hours. Then per-id change history. | Daily ID exports `https://files.tmdb.org/p/exports/<name>_MM_DD_YYYY.json.gz`, one JSON object per line, ready by ~08:00 UTC, kept 3 months. IDs plus `adult/video/popularity`, "not intended to be full data exports". | "somewhere in the 40 requests per second range", honour 429. Terms of use list "cache for longer than 6 months" as not allowed, and commercial use is not covered by the licence. | [changes guide](https://developer.themoviedb.org/docs/tracking-content-changes), [changes reference](https://developer.themoviedb.org/reference/changes-movie-list), [exports](https://developer.themoviedb.org/docs/daily-id-exports), [rate limits](https://developer.themoviedb.org/docs/rate-limiting), [terms](https://www.themoviedb.org/api-terms-of-use) |
| TMDb `/find` | Looks up by `imdb_id`, `tvdb_id`, `wikidata_id` and more, for movie, tv, season, episode, person | | | [find reference](https://developer.themoviedb.org/reference/find-by-id) |
| TVDB v4 | `GET /updates?since=<epoch>&type=series\|movies\|episodes...&action=update\|delete&page=`. `methodInt` 1=created, 2=updated, 3=deleted; deleted duplicates carry `mergeToType/mergeToId` | none found | Free under US$50k yearly revenue with attribution; paid tiers above (UNVERIFIED for open source) | [swagger.yml L2152-L2192](https://thetvdb.github.io/v4-api/swagger.yml), [api-information](https://thetvdb.com/api-information) |
| TVmaze | `GET /updates/shows?since=day\|week\|month`. Returns a flat `{ "<show id>": <unix timestamp> }` map (I fetched it live). A change to an episode also bumps the show. | Show index is paged 250 per page; their guide says to resume a daily/weekly sync from the page where you left off | 20 calls per 10 s per IP; output cached 60 min by their load balancers | [tvmaze.com/api](https://www.tvmaze.com/api), [live sample](https://api.tvmaze.com/updates/shows?since=day) |
| IMDb datasets | Whole files only, refreshed daily | `title.basics`, `title.akas`, `title.episode`, `title.ratings`, `title.crew`, `title.principals`, `name.basics` as gzipped TSV | "personal and non-commercial use" (check whether our site fits: UNVERIFIED) | [data.imdb.com](https://data.imdb.com/non-commercial-datasets/) |
| Wikidata | Weekly JSON dumps (about 130 GiB in Jan 2024) and 24-hour incremental dumps | Not for our box. Per-item `Special:EntityData` is fine for single lookups. Query service is poor when results are a big share of the data. | User-Agent policy, honour `Retry-After` | [Database download](https://www.wikidata.org/wiki/Wikidata:Database_download), [Data access](https://www.wikidata.org/wiki/Wikidata:Data_access) |
| Wikidata id properties | Distinct-values constraint: "the same ID should not be assigned to multiple items". P4947 TMDb movie id, P4835 TVDB series id, P345 IMDb id (`tt` = titles, `nm` = people) | | Useful as a cross-id "crosswalk" | [P4947](https://www.wikidata.org/wiki/Property:P4947), [P4835](https://www.wikidata.org/wiki/Property:P4835), [P345](https://www.wikidata.org/wiki/Property:P345) |

Takeaway: all three providers we use (TMDb, TVDB, TVmaze) offer a "what changed" feed. Our `discover_*` calls ignore all three and page through the catalog.

---

## 3. Standard patterns

Each pattern: what it is, who uses it (with evidence), what problem of ours it solves.

### (a) Incremental sync from a change feed plus a stored watermark

- What: ask "what changed since T?", fetch only those, then store T (the time the run started, not ended). Subtract a small overlap and make the saves safe to repeat.
- Used by: Radarr ([RefreshMovieService L256-L282](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/Movies/RefreshMovieService.cs#L256-L282), with a 15-minute overlap in [SkyHookProxy L55-L70](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/MetadataSource/SkyHook/SkyHookProxy.cs#L55-L70)); Overseerr (`lastScan` minus 10 minutes, [plex/index.ts L84-L128](https://github.com/sct/overseerr/blob/98ea135f2d370faba0362d259fccf51d8fd44a16/server/lib/scanners/plex/index.ts#L84-L128)); Trakt's own advice ([movies/index.ts L433-L445](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/api/src/contracts/movies/index.ts#L433-L445)).
- Rules from the evidence: keep the watermark per provider and per stream; advance it only after the batch is saved; if the gap is bigger than the feed window (TMDb: 14 days), fall back to tiers or a re-crawl, exactly like Radarr.
- Ours: `DiscoveryState` stores a page number, not a time. After "fully synced" it re-reads page 1 only, so a show edited on TVDB last week is never revisited. See section 4.

### (b) Bulk files for the first load

- What: download one file instead of making many calls. TMDb daily ID export, IMDb TSV datasets, Wikidata dumps.
- Used by: none of the apps above clearly ingest dumps (UNVERIFIED for Plex and Trakt); the providers publish them for this purpose ([TMDb exports](https://developer.themoviedb.org/docs/daily-id-exports), [IMDb](https://data.imdb.com/non-commercial-datasets/)).
- Careful: the TMDb file is a list of ids with a few filter fields, not details. It tells us which ids exist (and `popularity`, so we can skip the long tail). Details still come from the API, in a rate-limited queue. Wikidata full dumps are far too big for a 1 GB box; use them only elsewhere, or not at all.
- Solves: our "walk 500 pages" full sync and its restarts.

### (c) Pipeline stages and idempotent saves

- What: fetch -> normalise -> resolve identity -> save -> enrich, each stage a separate function that can be tested alone, with saves that give the same result if run twice.
- Used by: Plex's contract splits match from metadata ([API Endpoints.md L107](https://github.com/plexinc/tmdb-example-provider/blob/3348a89009bb418e083646fbe1360f544774bf71/docs/API%20Endpoints.md)); Jellyfin splits provider fetch from `MergeData` and uses refresh modes ([MetadataService.cs](https://github.com/jellyfin/jellyfin/blob/61f9a9df23a46175de2b8bac0a6da47f807cafd0/MediaBrowser.Providers/Manager/MetadataService.cs)); Sonarr separates the metadata proxy call from the refresh service and the scan step.
- Database support for idempotent saves: `INSERT ... ON CONFLICT DO UPDATE` "guarantees an atomic INSERT or UPDATE outcome ... even under high concurrency" ([PostgreSQL INSERT](https://www.postgresql.org/docs/current/sql-insert.html)). Note the rule that one statement may not touch the same row twice, so de-duplicate inside the batch first.
- Ours: our episode save already does this ([episode_repo.py L92-L120](../../app/repositories/episode_repo.py)); our title save does not (section 4).

### (d) Id mapping and identity rules

- Two shapes exist.
  1. Ids as columns on the title row, with one provider as the declared key: Sonarr (`TvdbId` unique), Radarr (`TmdbId` unique), MediaManager and Yamtrack (`(provider, id)` unique).
  2. A dictionary or list of ids per title: Jellyfin `ProviderIds`, Trakt `ids`, Plex `Guid` list. Wikidata is the extreme version: one property per provider, with a constraint that the same id must not appear on two items ([P4947](https://www.wikidata.org/wiki/Property:P4947)).
- Every successful system ends up with a database-level unique rule, often after a clean-up migration (Sonarr 018/019, Radarr 186). The lesson is that app-side matching alone drifts into duplicates.
- Rules the sources support (inference from them, not one quote):
  - An id only identifies a title within its own type and provider. TMDb and TVDB number movies and series separately; Wikidata properties are also separate for movie and series (P4947 is movie, P4835 is series). We fixed this in 429574a.
  - Two titles with different ids from the same provider are different titles, whatever their names say. We fixed this in 1519420.
  - Title-and-year matching is a last resort, never an automatic merge when either side already has a conflicting id.
  - Cross-provider bridging should use ids the providers hand out (TMDb `/find` with `imdb_id`/`tvdb_id` ([find](https://developer.themoviedb.org/reference/find-by-id)), TVDB remote ids, TVmaze `externals`), not guessing.
  - Plex offers a `manual` mode that returns ranked candidates instead of auto-merging. The same idea can become a "needs review" list for us.

### (e) Work queues with per-provider rate limits and refresh tiers

- What: a table or queue of "titles due for refresh", ordered by priority, and one place that rate-limits each provider.
- Used by: Sonarr (tiers in [ShouldRefreshSeries](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Tv/ShouldRefreshSeries.cs#L28-L68), per-host limit in [HttpClient](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Common/Http/HttpClient.cs#L148-L151)); Radarr (tiers by status); MediaManager (non-ended only); Jellyfin (refresh interval in days); Overseerr (recent vs full).
- Celery detail: `rate_limit` "is a per worker instance rate limit, and not a global rate limit. To enforce a global rate limit ... you must restrict to a given queue" ([Celery tasks guide](https://docs.celeryq.dev/en/stable/userguide/tasks.html)). So a single-concurrency "provider" queue is the simple way to get a global limit. Our TVmaze limiter keeps its call times in process memory ([tvmaze_provider.py L62-L73](../../app/services/providers/tvmaze_provider.py)), so two worker processes would each allow 20 calls per 10 s.
- Solves: "one slow enrichment run starves the worker" and "the same rows are picked again and again".

### (f) Job design in Celery

All from the Celery docs unless noted.

- **Split fast and slow work.** "If you have many tasks with a long duration you want the multiplier value to be one"; for mixed workloads "the best option is to use two worker nodes that are configured separately, and route the tasks according to the run-time" ([Optimizing](https://docs.celeryq.dev/en/stable/userguide/optimizing.html)). Queues are set with `task_queues`/`task_routes` and workers consume with `-Q` ([Routing](https://docs.celeryq.dev/en/stable/userguide/routing.html)). MediaWiki does the same thing: notification jobs run first on every cycle, and the manual recommends "separate runners" for the slow video jobs ([Job queue](https://www.mediawiki.org/wiki/Manual:Job_queue)).
- **Small tasks.** "It is better to split the problem up into many small tasks rather than have a few long running tasks" ([Tasks, Granularity](https://docs.celeryq.dev/en/stable/userguide/tasks.html)). Chunked self-rescheduling (process N items or T seconds, save the cursor, enqueue the next chunk) is common practice, but I did not find Celery documenting it as a named pattern (UNVERIFIED as a standard). Overseerr's bundle-of-20 loop is a code example of the same shape ([baseScanner.ts L16-L17](https://github.com/sct/overseerr/blob/98ea135f2d370faba0362d259fccf51d8fd44a16/server/lib/scanners/baseScanner.ts#L16-L17)).
- **Time limits.** Hard limit kills the process; soft limit raises `SoftTimeLimitExceeded` so the task can stop cleanly ([Configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html)). The default is no limit at all.
- **acks_late.** Default is to acknowledge before running. `task_acks_late` acknowledges after, so a crashed task is redelivered; the docs say tasks should then be idempotent. With Redis, an unacknowledged message is redelivered after the visibility timeout (default 1 hour) and the docs warn it "will be executed again, and again in a loop" for long ETA/countdown/retry tasks ([Redis broker caveats](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)). The docs describe this for ETA/countdown/retry tasks; applying it to any `acks_late` task that runs over an hour is my inference.
- **Prefetch.** `worker_prefetch_multiplier=1` with `acks_late` is the documented setup for long tasks. We already have it ([celery_app.py L18-L19](../../app/celery_app.py)).
- **Beat.** "You have to ensure only a single scheduler is running ... otherwise you'd end up with duplicate tasks." Beat does not wait for the previous run: "the tasks may overlap if the first task doesn't complete before the next ... use a locking strategy" ([Periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)). A DB-backed scheduler exists (`django-celery-beat`, used by Yamtrack), but it is Django specific. Schedule entries accept `expires` through `options`.
- **Locks.** The Celery cookbook recipe uses an atomic `cache.add(lock_id, ...)` with an expiry and warns "your tasks run-time shouldn't exceed the timeout" ([Task cookbook](https://docs.celeryq.dev/en/stable/tutorials/task-cookbook.html)). With Redis that is `SET key value NX EX seconds`. Sonarr's queue does the same job by refusing a command equal to one already queued or started ([CommandQueueManager L101-L125](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Messaging/Commands/CommandQueueManager.cs#L101-L125)).
- **Postgres-based alternative.** Procrastinate has `lock` (jobs with the same lock run one at a time) and `queueing_lock` (only one waiting job per key, otherwise `AlreadyEnqueued`) and defers each cron period exactly once, "even with multiple workers" ([locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/locks.html), [queueing locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/queueing_locks.html), [cron](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html)). Good design, wrong place for us because of the 270 ms database link (inference).

### (g) Batch writes and few round trips

- PostgreSQL's own guidance: one transaction for many inserts; `COPY` "is almost always faster than using INSERT, even if PREPARE is used and multiple insertions are batched" ([Populating a Database](https://www.postgresql.org/docs/current/populate.html)). Multi-row `INSERT ... ON CONFLICT` is the middle ground and is what most apps can use.
- SQLAlchemy 2.0 already batches `executemany` inserts into multi-row statements, 1000 rows per statement by default, tunable with `insertmanyvalues_page_size` ([SQLAlchemy connections guide](https://docs.sqlalchemy.org/en/20/core/connections.html)).
- Rough arithmetic (my estimate, not a measurement): at 270 ms per round trip, 3 statements per title is about 0.8 s per title, so 500 titles take about 7 minutes. Five statements per 500-title chunk take about 1.4 seconds.
- Ours: commits 304d1a2 and f9959dd already did this for titles and episodes. Remaining per-row work is listed in section 4.

### (h) Read model vs source of truth, and caching

- Trakt says it outright: the summary endpoint is canonical and embedded copies are "snapshots" ([caching-and-fresh-data.md](https://github.com/trakt/trakt-api/blob/dadb51b8efa5f011bab319b52f5f497800dddefe/projects/developer/src/lib/guides/caching-and-fresh-data.md)).
- Radarr keeps provider data in `MovieMetadata` and user state in `Movie` ([MovieMetadata.cs](https://github.com/Radarr/Radarr/blob/b3396e2fd872c03a07b2bc98144715ae1bd88032/src/NzbDrone.Core/Movies/MovieMetadata.cs)).
- A caching proxy in front of the providers is used by Sonarr (SkyHook), Radarr and MediaManager (`metadata_relay`). TVmaze caches every answer for 60 minutes and says to allow up to an hour for updates to appear ([tvmaze.com/api](https://www.tvmaze.com/api)). Wikidata says cached URLs may give faster responses ([Data access](https://www.wikidata.org/wiki/Wikidata:Data_access)).
- Licence note that shapes the design: the TMDb terms list caching "for longer than 6 months" among things you may not do. So data from TMDb has to be refreshed or purged within 6 months. A refresh-tier floor of about 180 days (which is what Radarr uses) fits that. Re-read the terms page before relying on it, since I only read an excerpt.
- Ours: user tables (library, reminders, rankings) are already separate from `content`. Our embedding uses a content hash (`embedding_hash`) to know when to recompute ([content.py L36-L39](../../app/models/content.py)), which is a good derived-data pattern worth reusing for other derived data.

---

## 4. Gap analysis of our code

Files read: `app/services/content_discovery.py`, `app/repositories/content_repo.py`, `app/repositories/episode_repo.py`, `app/tasks/periodic.py`, `app/celery_app.py`, `app/models/content.py`, `app/models/discovery_state.py`, `app/services/providers/*`, `docker-compose.yml`, `docs/ARCHITECTURE.md`, `docs/DATA_FLOWS.md`, `docs/PROVIDERS.md`, `docs/adr/`.

### 4.1 Where we already match a standard

| Pattern | Our code |
|---|---|
| Adapter per provider that returns one common shape | `ContentProvider` + `NormalizedContent` ([providers/base.py](../../app/services/providers/base.py)) |
| Cursor per provider | `DiscoveryState` ([discovery_state.py](../../app/models/discovery_state.py)) |
| Cursor moved in the same database transaction as the data | `_discover` commits once after saving ([content_discovery.py L291-L325](../../app/services/content_discovery.py)) |
| Batched, chunked writes | `bulk_upsert_normalized` and episode `ON CONFLICT` ([content_repo.py L392-L453](../../app/repositories/content_repo.py), [episode_repo.py L92-L120](../../app/repositories/episode_repo.py)) |
| Time budget on a long job | `time_budget_seconds` ([content_discovery.py L356-L407](../../app/services/content_discovery.py)) |
| Late ack plus prefetch 1 | [celery_app.py L18-L19](../../app/celery_app.py) |
| One beat only | [docker-compose.yml L35-L50](../../docker-compose.yml) comment |
| Same-provider id conflict never merges; id scoped by content type | `_ids_conflict`, `_first_by_numeric_id` |
| Separate user data and catalog | library/reminder/rank tables vs `content` |
| Derived-data invalidation by hash | `embedding_hash` |

### 4.2 Where we deviate, and which problem each explains

| # | Deviation | Evidence in our code | Problem it explains | Standard it breaks |
|---|---|---|---|---|
| G1 | A failed provider call looks the same as "end of catalog". Every provider catches its errors and returns `[]` (TVDB [L205-L239](../../app/services/providers/tvdb_provider.py), TVmaze `_get_json` [L75-L90](../../app/services/providers/tvmaze_provider.py)). `_walk_pages` treats an empty list as the end and calls `_mark_fully_synced` ([content_discovery.py L184-L186](../../app/services/content_discovery.py)). A TVmaze page whose shows are all filtered out (weight under 70, not running, not English, [L240-L266](../../app/services/providers/tvmaze_provider.py)) is also empty. | One timeout or 429 can flip a provider to "fully synced", after which it only re-reads page 1 and the tail. This is consistent with "jobs that never finish the catalog". I did not reproduce it against a live database, so treat it as a code-reading finding (see section 7). | Sonarr and Radarr catch errors per title and mark the result "indeterminate" instead of treating it as success ([RefreshSeriesService L224-L246](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Tv/RefreshSeriesService.cs#L224-L246)) |
| G2 | No per-title refresh bookkeeping. `_find_sparse` picks titles where `episodes IS NULL` (TV), else `runtime IS NULL`, ordered by id ([L432-L452](../../app/services/content_discovery.py)). A show with no usable id, or whose provider returns no episodes, never gets `episodes` set, so it is picked first on every run, ahead of everything after it. Tier 2 is not reached while any TV show is missing episodes. | One group of unlucky rows can occupy every enrichment run ("re-run from the start, never finish"). Two overlapping runs (beat fires every 15 minutes with no lock) pick the same 50 rows. | Sonarr/Radarr keep `LastInfoSync` per item and decide from it ([ShouldRefreshSeries](https://github.com/Sonarr/Sonarr/blob/59c22e85993bb1120bfcf9fd1d6f509a510203df/src/NzbDrone.Core/Tv/ShouldRefreshSeries.cs#L28-L68)) |
| G3 | One queue, default concurrency, no time limits, no `expires`, no lock. `celery_app.py` has no `task_queues`, `task_routes`, `task_time_limit` or `expires`. Compose starts one worker with default concurrency (number of CPUs: 2) ([docker-compose.yml L30](../../docker-compose.yml)). Reminders run every minute ([config.py L73](../../app/config.py)); enrichment every 15 minutes with an 8-minute budget; discovery every 6 hours and then also enriches 30 titles with no budget ([periodic.py L18-L34](../../app/tasks/periodic.py)); re-ranking loops over all users. | Two slow tasks fill both slots and every minute's reminder waits behind them. Beat keeps queueing a reminder each minute, so a backlog builds and drains late. | Celery: split fast and slow ([Optimizing](https://docs.celeryq.dev/en/stable/userguide/optimizing.html)); beat overlap needs a lock ([Periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)) |
| G4 | Retry restarts the whole job. `raise self.retry(exc=exc)` after any error, up to 3 times, 60 s apart, rerunning from the start ([periodic.py L18-L34](../../app/tasks/periodic.py)). | "Scheduled jobs that re-run from the start". Without a cursor inside the job, progress made before the error is repeated or lost. | Overseerr/Radarr: watermark advanced only after a good run; per-item error handling |
| G5 | Identity is enforced only in Python. `content` has plain indexes on `tmdb_id`, `imdb_id`, `tvdb_id`, `tvmaze_id` but no `UNIQUE` ([content.py L41-L50](../../app/models/content.py)). Matching is done by `SELECT` first, then an insert that has no `ON CONFLICT` ([content_repo.py L405-L453](../../app/repositories/content_repo.py)). | Two overlapping runs, or two workers, can both see "not found" and both insert, giving duplicates. This is the exact failure Sonarr (018/019) and Radarr (186) had to repair by migration. | DB-level unique ids |
| G6 | Ids live as 4 columns. Adding a provider means a new column, a new `if` in `_external_id_for` ([L509-L518](../../app/services/content_discovery.py)) and a new loop key in `_ExistingIndex`/`_PendingIndex`/`_ids_conflict`. Ids in `NormalizedContent` are typed `int` for TMDb in code but `str` in docs. | Mis-merges and silent misses when a provider id is missing, and a growing set of places to edit. | Jellyfin `ProviderIds`, Trakt `ids`, Plex `Guid` list |
| G7 | Refresh can never correct stale data. `_merge_into` and the episode `COALESCE` fill blanks only ([content_repo.py L483-L530](../../app/repositories/content_repo.py), [episode_repo.py L112-L118](../../app/repositories/episode_repo.py)). Only `next_episode_date` is overwritten. | `status` set to "Running" stays "Running" after the show ends; ratings never move; a rescheduled episode keeps its old `air_date`. For a tracker that sends reminders, a wrong air date is a user-visible bug. Revisiting a title adds nothing unless a field was empty, so even a perfect refresh schedule would not help yet. | Jellyfin's `MetadataRefreshMode.FullRefresh` + `LockedFields`: refresh overwrites unless the field is locked |
| G8 | Paging the whole catalog instead of using change feeds. `discover_tv_shows(page)` and `get_all_series(page)` are the only sync entry points; none of TMDb `/changes`, TVmaze `/updates/shows`, TVDB `/updates` is used (no match in `app/services/providers`). | Large amount of work for each refresh, and a title changed on the provider is only noticed if it happens to be on page 1. | Radarr, Overseerr, Trakt advice |
| G9 | Per-row work still inside discovery. `_fill_new_movie_release_dates` does one database lookup and one HTTP call per new TVDB movie ([L268-L289](../../app/services/content_discovery.py)). Enrichment commits once per title and calls providers one title at a time ([L405-L427](../../app/services/content_discovery.py)). TMDb opens a new HTTP client for every call ([tmdb_provider.py L48](../../app/services/providers/tmdb_provider.py)). | With 270 ms to the database, each per-title lookup is a visible stall; a new connection per TMDb call adds a TLS handshake each time (inference). | Batch writes; keep-alive clients |
| G10 | Provider rate limit is per process. The TVmaze limiter is an in-memory deque ([L62-L73](../../app/services/providers/tvmaze_provider.py)); TMDb, TVDB have none. | Two worker processes or an overlapping run can exceed 20 calls/10 s. | Celery per-worker limit note; Sonarr per-host limit |
| G11 | Docs drift. `ARCHITECTURE.md` and `DATA_FLOWS.md` still say APScheduler and `scheduler.py` (the code uses Celery). `PROVIDERS.md` names `DiscoveryState` columns `provider_name`/`last_run_at` (code: `provider`/`last_synced_at`) and says "resets to page 1", and says `get_episodes` returns `list[dict]` (code returns `NormalizedEpisode`). | Wrong mental model for anyone designing from the docs (including future agents). | |

### 4.3 SOLID and design-pattern issues

- **Single responsibility.** `ContentDiscoveryService` (518 lines) does cursor handling, fetching, in-memory de-duplication, release-date fill, enrichment selection and execution, search and trending. `ContentRepository` (587 lines) holds queries, business matching (`_ExistingIndex`, `_PendingIndex`, `_merge_into`) and a legacy path that knows TMDb image URLs (`_create_from_api`, [L549-L570](../../app/repositories/content_repo.py)). A repository should store and fetch; matching rules belong in a resolver.
- **Duplicated rules.** `_ids_conflict` and the id-then-title matching exist twice (service `_deduplicate` and repo `_ExistingIndex`/`_PendingIndex`), so they can drift apart. The recent identity fixes had to be applied in both places.
- **Open/closed.** `_external_id_for` is an `if provider.name == ...` chain; the service also does `p.name == "tvdb" and hasattr(p, "get_movie_release")` ([L275](../../app/services/content_discovery.py)). That is the provider interface leaking into the service.
- **Interface segregation / Liskov.** The `ContentProvider` ABC makes every provider implement `discover_movies`, `discover_tv_shows`, `search`, `get_upcoming`; TVmaze returns `[]` for movies. The meaning of `[]` is undefined (end? error? unsupported?), which is G1. Providers have no declared capabilities (supports changes feed? supports episodes? which id kinds?).
- **Policy inside an adapter.** TVmaze's "weight at least 70, running, English" filter ([L240-L266](../../app/services/providers/tvmaze_provider.py)) is a product decision hidden in a provider.
- **Fetch / match / save / schedule mixed.** `_discover` fetches, merges, fills dates, saves and commits in one method; `periodic.py` tasks contain retry and orchestration; the cursor logic lives next to the fetch loop.
- **Patterns that fit and are missing:** Adapter (have), Repository (have, but overloaded), Strategy for per-provider id mapping (missing), a Resolver/Matcher object for identity (missing, currently spread across three places), a Unit of Work per chunk (partial), Lease/Lock for jobs (missing), Specification for "due for refresh" (missing; today a hard-coded query).

---

## 5. Options and recommendation

Constraints: one developer, one 2 CPU / ~1 GB box, a database 270 ms away, free tiers only.

### Option A: Harden in place (small)

Keep tables and module layout. Fix G1, G3, G4, G2, and add `ON CONFLICT` plus a unique index where data allows.

- Pros: days of work, no schema redesign, immediate relief for reminders and runaway enrichment.
- Cons: ids stay as columns; no change feeds; stale data still never corrected (G7); the service stays a 500-line class.

### Option B: Staged pipeline on the same Celery + Redis (medium) - recommended

Option A, plus:

- `title_external_ids` table with a `UNIQUE (provider, kind, external_id)`; the resolver picks match / create / conflict.
- Per-title refresh columns (`last_refreshed_at`, `next_refresh_at`, `refresh_attempts`, `last_error`) and a "due titles" query with tiers.
- `sync_state` per (provider, stream) holding a timestamp watermark and a lease.
- Change feeds for TMDb, TVmaze, TVDB, with tiers as fallback.
- Providers split into small capabilities (fetch changes, fetch details, search) that raise on failure.
- Two queues and two small worker processes.
- Refresh overwrites provider-owned fields (with a "locked/manual" flag where we edit by hand).

- Pros: matches what Radarr/Sonarr/Overseerr do; each step ships alone; no new infrastructure; fixes every item in section 4.
- Cons: a data migration (id backfill and duplicate audit) and more modules to learn.

### Option C: Put the sync worker next to the database (infrastructure option, can combine with A or B)

Run the discovery/enrichment worker on the GCP VM that hosts Postgres, and keep only the web app and reminders on the Oracle box. Round trips drop from about 270 ms to near zero, so per-row writes stop mattering.

- Pros: removes the cause of the slow-write class of problems rather than the symptom.
- Cons: depends on whether that VM has room for another process (UNVERIFIED, I have no data on its spare CPU or RAM and did not touch any server); a second deploy target to keep running; provider API calls then leave from a different network (check provider IP rules, for example TVmaze's per-IP limit).

### Not recommended

- A Postgres-based queue (Procrastinate, `taskiq-postgresql` as MediaManager uses): every poll and lock would cross the 270 ms link. Revisit only if the worker moves next to the database (Option C) and Redis becomes a burden.
- Kafka, Airflow, Kubernetes, Debezium, a search cluster: no source I read uses them at this scale. Sonarr, Radarr, Jellyfin, Overseerr and Yamtrack manage catalogs with a single process and a small queue.
- Loading Wikidata dumps (about 130 GiB) on this box.
- Machine-learning or fuzzy matching for identity: use provider-supplied ids first; keep fuzzy matching only for a review list.

### Recommendation

**Option B, started with Option A's items as Phase 1 and 2, and evaluate Option C only if write latency is still a problem after Phase 3.** Reasons: the evidence says state per title, a watermark per provider, and a database unique rule are the three things every working catalog sync has, and we have none of them yet. Everything else is optional polish.

### Target design (Option B)

**Module boundaries** (names are suggestions):

```
app/sync/
  providers/      fetch + normalise only. Raise ProviderError on failure. Never return [] for an error.
                  Each provider declares capabilities: changes_since(), details(id), episodes(id), search(q)
  identity.py     Resolver: (NormalizedContent, id index) -> Match(content_id) | Create | Conflict(review)
                  Pure, no database calls inside; takes a lookup object. All id and title rules in one place.
  store.py        Batched writes only (multi-row INSERT ... ON CONFLICT), one transaction per chunk
  planner.py      "What is due?": change feed results and the tier query; claims a batch with a lease
  pipeline.py     fetch -> normalise -> resolve -> store for one chunk; returns counts
app/tasks/        thin: take the lock, call planner + pipeline within a time budget, release
```

**Data model changes**

```sql
-- one row per provider id
CREATE TABLE content_external_id (
  content_id  int  NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  provider    text NOT NULL,          -- 'tmdb' | 'tvdb' | 'imdb' | 'tvmaze' ...
  kind        text NOT NULL,          -- 'movie' | 'tv_show'  (id spaces are separate per type)
  external_id text NOT NULL,
  PRIMARY KEY (provider, kind, external_id)       -- the database is the final judge
);
CREATE INDEX ON content_external_id (content_id);

-- per-title refresh state
ALTER TABLE content ADD COLUMN last_refreshed_at timestamptz,
                    ADD COLUMN next_refresh_at   timestamptz,
                    ADD COLUMN refresh_attempts  int NOT NULL DEFAULT 0,
                    ADD COLUMN last_error        text;
CREATE INDEX ON content (next_refresh_at);

-- provider streams (extends discovery_state)
-- (provider, stream) -> watermark timestamptz, status, lease_until, last_error
```

Keep the four id columns for now as read-through copies, so pages and queries do not change in the same release (inference: lowers risk; remove later).

**Refresh tiers** (modelled on Sonarr/Radarr; numbers are a starting point to tune):

| Tier | Which titles | Refresh |
|---|---|---|
| Hot | Tracked by any user, or upcoming episode/release within 14 days | 6 hours (Sonarr uses 6 h for non-ended) |
| Warm | Running shows, announced or in-cinema movies | 12 hours to 1 day |
| Cold | Ended shows and released movies | 30 days (Sonarr) up to 180 days (Radarr; also fits the TMDb 6-month cache limit) |
| Failed | `refresh_attempts` at least 3 | exponential backoff, capped at 7 days, listed in a report |

**Queues and workers (fits 1 GB)**

| Queue | Tasks | Worker |
|---|---|---|
| `fast` | reminders, cleanup, anything under a few seconds | `celery worker -Q fast -c 1` |
| `sync` | discovery, change-feed sync, enrichment chunks. Concurrency 1 gives a global provider rate limit for free ([Celery per-worker limit](https://docs.celeryq.dev/en/stable/userguide/tasks.html)) | `celery worker -Q sync,slow -c 1` |
| `slow` | embeddings, re-ranking, gossip | same worker as `sync`, lower priority, or its own when RAM allows |

Memory per Celery worker process on our box is UNVERIFIED; measure before committing to a third process.

**Job rules for every periodic task**

1. `expires` on the beat entry, equal to its interval, so stale copies are dropped instead of piling up.
2. `soft_time_limit` a little under the interval and `time_limit` about 30 s after it; the task catches `SoftTimeLimitExceeded`, saves its cursor and returns.
3. A Redis lease (`SET lock NX EX`) per job name, in the style of the Celery cookbook, so overlapping beats exit at once.
4. Process one chunk (N titles or T seconds), commit the cursor and the data together, then stop. If work remains the next beat tick continues; use an explicit self-enqueue only for the one-time backfill.
5. No `self.retry` that restarts a whole run; failures are recorded per title (`refresh_attempts`, `last_error`) and the title is retried later.
6. Idempotent saves (`ON CONFLICT`), so a redelivered message (acks_late) does no harm.

**Incremental sync design**

- TMDb: `/movie/changes` and `/tv/changes` between watermark minus overlap and now, page through at 100 per page, queue those ids if we already have them. If the gap exceeds 14 days, fall back to the tier query.
- TVmaze: `/updates/shows?since=day|week|month`, choose the smallest window that covers the gap; compare timestamps with ours.
- TVDB: `/updates?since=<epoch>&type=series` (and `movies`, `episodes`); honour `methodInt=3` (delete) and `mergeToId` (duplicate merged) by updating our id table.
- New titles that we do not yet know come from the existing page walk (kept at a slow pace) and, for the initial load, the TMDb daily ID export filtered by popularity.

**Identity rules (in `identity.py`)**

1. Exact `(provider, kind, external_id)` hit in `content_external_id`: same title.
2. Otherwise, if the incoming item carries several ids, look each up. If they point at two different titles, record a Conflict (do not merge, do not create); write it to a review table.
3. If an existing title has a different id of the same provider and kind, they are different titles (already our rule).
4. Create a new title only with at least one id, or with title + year + type when no ids exist at all. Title-only merges never happen automatically; a title + year hit with a conflicting or missing id becomes a review candidate.
5. After create, `INSERT ... ON CONFLICT DO NOTHING` on the id table, then re-read; the loser of a race becomes an update.
6. Bridge providers with ids they supply: TMDb `/find` (`imdb_id`, `tvdb_id`), TVDB remote ids, TVmaze `externals`.

**Adopt now / later / never**

| When | What |
|---|---|
| Now | Providers raise on error (G1); two queues, expires, time limits, lock (G3); per-title refresh state (G2); refresh may overwrite provider-owned fields (G7); `UNIQUE` ids after an audit |
| Soon | `content_external_id` table and resolver; change feeds and watermarks; Redis cache of provider GETs; shared rate limiter |
| Later | TMDb daily export backfill; review UI for conflicts; moving the worker next to the database (Option C); removing the old id columns |
| Never (for now) | Kafka, Airflow, Kubernetes, Postgres queue, Wikidata dumps, ML matching |

---

## 6. Phased plan

Each phase ships on its own. "Fixes" refers to our problem list: S = slow per-row writes, W = worker starved / reminders late, R = jobs re-run from the start or never finish, D = duplicate or mis-merged titles, B = no clear separation of fetch / normalise / match / save.

### Phase 0: Failure is not "the end" (1 to 2 days)

- Change: providers raise `ProviderError` (or return a result with `ok`, `items`, `has_more`) instead of `[]` on failure. `_walk_pages` marks `fully_synced` only on a real empty page, and not when the page was empty because of a client-side filter (count raw items before filtering). On error the cursor does not advance and the run stops cleanly.
- Fixes: R (premature "fully synced" / never finishes), part of B.
- Tests: a fake provider that raises on page 3 and checks `last_page` stays 2 and `fully_synced` is False; one returning a real empty page flips it; one returning a page where TVmaze filters out everything keeps the cursor moving; existing `test_discovery_new_pages.py`, `test_discovery_ids.py` still pass.

### Phase 1: Queues, limits and locks (1 to 2 days)

- Change: `task_queues`/`task_routes` for `fast` and `sync`; two worker commands in compose; `expires` on every beat entry; `soft_time_limit` and `time_limit` per task; Redis lease around discovery and enrichment; remove the unbudgeted `enrich_sparse_content` call from `content_discovery_task`.
- Fixes: W (reminders no longer wait), R (overlapping runs), part of S (no run outlasts its slot).
- Tests: unit test that `celery_app.conf.task_routes` sends `reminder_task` to `fast`; a lock test (second acquire fails, expiry releases); a task test that raises `SoftTimeLimitExceeded` and checks the cursor was saved; a manual check on the box that a long enrichment does not delay a reminder (measure queue wait).

### Phase 2: Per-title refresh state and a fair "due" query (2 to 3 days)

- Change: add `last_refreshed_at`, `next_refresh_at`, `refresh_attempts`, `last_error`; replace `_find_sparse` with "due titles ordered by `next_refresh_at`", claimed with `FOR UPDATE SKIP LOCKED` or the lease from Phase 1; set the next due time from the tier table; failures back off instead of blocking; let refresh overwrite provider-owned fields (keep a manual-override flag if any field is edited by hand).
- Fixes: R (no more head-of-line titles), W (bounded runs), user-visible staleness (G7).
- Tests: a title that always fails is skipped on the next run and returns after its backoff; two concurrent claims never return the same row; a changed `status`/`air_date` is applied; tier boundaries (6 h, 30 d) as table-driven tests.

### Phase 3: Batch every remaining write and read (2 to 3 days)

- Change: `INSERT ... ON CONFLICT` for `content` (using the unique ids from Phase 4 once present; until then keep the select-then-insert path but commit per chunk); drop per-title lookups in `_fill_new_movie_release_dates` (batch the existence check; fetch details through the queue instead of inside discovery); reuse one HTTP client per provider; set `insertmanyvalues_page_size` deliberately.
- Fixes: S.
- Tests: statement-count tests (the repo already has `test_enrichment_speed.py` and `test_bulk_save.py`; extend them to assert a fixed number of statements for 500 titles); an integration run against Postgres with an artificial 270 ms delay on the connection to confirm total time.

### Phase 4: External ids table and resolver (3 to 5 days)

- Change: migration to create `content_external_id`, backfill from the four columns, an audit report of duplicates (same `(provider, kind, id)` on several rows) reviewed by hand, then the `PRIMARY KEY`/unique rule. Extract `identity.py` and delete the duplicated rules in the service and repository. Conflicts go to a review table instead of being merged or dropped.
- Fixes: D, B.
- Tests: table-driven resolver tests including every past bug (non-Latin titles, same title different ids, movie id equal to a series id); a two-session race test (two writers, same new title, one row results); a migration test (`test_migrations.py` exists) on a copy of production-shaped data; a property test that merging in any order gives the same final mapping.

### Phase 5: Change feeds and watermarks (3 to 5 days)

- Change: `sync_state` per (provider, stream) with a timestamp watermark and overlap; implement `changes_since` for TVmaze (simplest), then TMDb, then TVDB; tier query as fallback when the gap is too large (as in Radarr); watermark advanced only after the chunk is saved.
- Fixes: R (restarts continue from the watermark), S (far fewer titles per run), staleness.
- Tests: fake feed returns 3 ids and the run touches exactly those 3; watermark does not move on failure; a gap of more than 14 days falls back to tiers; duplicate ids in two feeds are fetched once; delete/merge records from TVDB are applied.

### Phase 6: Backfill and cleanup (optional, as needed)

- Change: TMDb daily ID export loader (stream the gzip line by line, filter by popularity, enqueue unknown ids at a slow pace); split `ContentDiscoveryService` into the modules above; fix `ARCHITECTURE.md`, `DATA_FLOWS.md`, `PROVIDERS.md` to match; optionally evaluate Option C.
- Fixes: B, onboarding new providers without touching the service.
- Tests: loader unit test on a small fixture file; provider contract tests that every provider raises on HTTP failure and declares capabilities.

---

## 7. Open questions and UNVERIFIED list

Open questions for the owner:

1. Is Scene Sentry a free, non-commercial site? That decides TMDb (commercial use not covered), IMDb datasets (non-commercial only) and TVDB (free under US$50k revenue, with attribution) terms.
2. Do users edit catalog fields by hand? If yes, we need a manual-override flag before letting refresh overwrite.
3. Does the GCP VM that holds Postgres have spare CPU and memory for a worker (Option C)?
4. Which titles should the "hot" tier include: only library items, or also trending?

UNVERIFIED (could not confirm from a primary source):

- Sonarr's and Radarr's metadata server (SkyHook) source and how it syncs from TVDB/TMDb: not in the cloned repos.
- Whether Plex, Trakt or Letterboxd use bulk dumps internally: no primary source found.
- Kodi scraper behaviour: the Kodi wiki returned 403, so no claim is made.
- Netflix: I only saw search excerpts of the NMDB posts; they concern media timeline data, not third-party catalog ingestion, so I did not use them.
- Celery redelivering `acks_late` tasks that run longer than the Redis visibility timeout: the docs describe the visibility timeout for ETA/countdown/retry tasks; extending it to long-running `acks_late` tasks is my inference.
- Chunked self-rescheduling as a documented "standard": I found working examples (Overseerr loops, Radarr's per-run batches) but no standard text that names it.
- TMDb "6 months" cache rule: read as an excerpt from the terms page (a list of prohibited acts). Re-read the full page before relying on it.
- IMDb dataset licence fit for a free public website; TVDB terms for an open-source project beyond the revenue tiers page.
- Memory use of an extra Celery worker process on the Oracle box.
- The G1 premature "fully synced" path is from code reading; I did not run it against the live database or logs. Check `discovery_state` rows (`fully_synced`, `last_page`, `last_synced_at`) per provider to see whether it already happened.
- Whether the live `content` table has unique indexes added outside the Alembic files I saw (`alembic/versions` lists three migrations, none of which I opened line by line for constraints).
- Real per-statement timings over the 270 ms link: the estimates in section 3(g) are arithmetic, not measurements.

---

## 8. Source list

Code read (all cloned with `git clone --depth 1` on 2026-10-12; links pinned to the commit):

- Sonarr `59c22e85993bb1120bfcf9fd1d6f509a510203df`: `src/NzbDrone.Core/Tv/ShouldRefreshSeries.cs`, `Tv/RefreshSeriesService.cs`, `Tv/Series.cs`, `Jobs/TaskManager.cs`, `Jobs/Scheduler.cs`, `Jobs/ScheduledTask.cs`, `Messaging/Commands/CommandQueueManager.cs`, `Messaging/Commands/CommandRepository.cs`, `Datastore/Migration/018_remove_duplicates.cs`, `019_restore_unique_constraints.cs`, `NzbDrone.Common/Http/HttpClient.cs`, `NzbDrone.Common/Cloud/SonarrCloudRequestBuilder.cs`. https://github.com/Sonarr/Sonarr
- Radarr `b3396e2fd872c03a07b2bc98144715ae1bd88032`: `src/NzbDrone.Core/Movies/RefreshMovieService.cs`, `Movies/ShouldRefreshMovie.cs`, `Movies/MovieMetadata.cs`, `MetadataSource/SkyHook/SkyHookProxy.cs`, `Datastore/Migration/186_fix_tmdb_duplicates.cs`. https://github.com/Radarr/Radarr
- Jellyfin `61f9a9df23a46175de2b8bac0a6da47f807cafd0`: `MediaBrowser.Model/Entities/IHasProviderIds.cs`, `MediaBrowser.Controller/Providers/IRemoteMetadataProvider.cs`, `MetadataRefreshMode.cs`, `MediaBrowser.Providers/Manager/MetadataService.cs`, `Emby.Server.Implementations/ScheduledTasks/ScheduledTaskWorker.cs`. https://github.com/jellyfin/jellyfin
- Overseerr `98ea135f2d370faba0362d259fccf51d8fd44a16`: `server/lib/scanners/baseScanner.ts`, `server/lib/scanners/plex/index.ts`, `server/job/schedule.ts`. https://github.com/sct/overseerr
- Trakt API repo `dadb51b8efa5f011bab319b52f5f497800dddefe`: `projects/api/src/contracts/movies/index.ts`, `projects/developer/src/lib/guides/{caching-and-fresh-data,rate-limiting,api-use-policy,standard-media-objects}.md`. https://github.com/trakt/trakt-api
- Yamtrack `5095564303dc873e5b6cc224941fbe068ddfddd7`: `src/config/settings.py`, `src/events/tasks.py`, `src/events/calendar/main.py`, `src/app/models.py`. https://github.com/FuzzyGrim/Yamtrack
- MediaManager `98f253238c780b462af42691154bf0d1f5723f92`: `media_manager/scheduler.py`, `tv/models.py`, `tv/metadata.py`, `metadata_relay/README.md`. https://github.com/maxdorninger/MediaManager
- Plex example provider `3348a89009bb418e083646fbe1360f544774bf71`: `README.md`, `docs/API Endpoints.md`, `docs/Metadata.md`. https://github.com/plexinc/tmdb-example-provider

Official docs and specs:

- TMDb: https://developer.themoviedb.org/docs/tracking-content-changes, https://developer.themoviedb.org/reference/changes-movie-list, https://developer.themoviedb.org/docs/daily-id-exports, https://developer.themoviedb.org/docs/rate-limiting, https://developer.themoviedb.org/reference/find-by-id, https://www.themoviedb.org/api-terms-of-use
- TVDB v4: https://thetvdb.github.io/v4-api/swagger.yml (the `/updates` path, lines 2152-2192), https://thetvdb.com/api-information
- TVmaze: https://www.tvmaze.com/api and a live call to https://api.tvmaze.com/updates/shows?since=day
- IMDb datasets: https://data.imdb.com/non-commercial-datasets/
- Wikidata: https://www.wikidata.org/wiki/Wikidata:Database_download, https://www.wikidata.org/wiki/Wikidata:Data_access, https://www.wikidata.org/wiki/Property:P4947, https://www.wikidata.org/wiki/Property:P4835, https://www.wikidata.org/wiki/Property:P345
- Celery: https://docs.celeryq.dev/en/stable/userguide/tasks.html, https://docs.celeryq.dev/en/stable/userguide/optimizing.html, https://docs.celeryq.dev/en/stable/userguide/routing.html, https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html, https://docs.celeryq.dev/en/stable/userguide/configuration.html, https://docs.celeryq.dev/en/stable/userguide/workers.html, https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html, https://docs.celeryq.dev/en/stable/tutorials/task-cookbook.html
- Procrastinate: https://procrastinate.readthedocs.io/en/stable/howto/advanced/locks.html, https://procrastinate.readthedocs.io/en/stable/howto/advanced/queueing_locks.html, https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html, https://procrastinate.readthedocs.io/en/stable/discussions.html
- PostgreSQL: https://www.postgresql.org/docs/current/sql-insert.html, https://www.postgresql.org/docs/current/populate.html, https://www.postgresql.org/docs/current/sql-select.html (locking clause, `SKIP LOCKED`)
- SQLAlchemy 2.0: https://docs.sqlalchemy.org/en/20/core/connections.html (insertmanyvalues)
- MediaWiki job queue: https://www.mediawiki.org/wiki/Manual:Job_queue

Our repo (relative to this file):

- [app/services/content_discovery.py](../../app/services/content_discovery.py), [app/repositories/content_repo.py](../../app/repositories/content_repo.py), [app/repositories/episode_repo.py](../../app/repositories/episode_repo.py), [app/tasks/periodic.py](../../app/tasks/periodic.py), [app/celery_app.py](../../app/celery_app.py), [app/models/content.py](../../app/models/content.py), [app/models/discovery_state.py](../../app/models/discovery_state.py), [app/services/providers/](../../app/services/providers/), [docker-compose.yml](../../docker-compose.yml), [docs/ARCHITECTURE.md](../ARCHITECTURE.md), [docs/DATA_FLOWS.md](../DATA_FLOWS.md), [docs/PROVIDERS.md](../PROVIDERS.md), [docs/adr/](../adr/)
