# ADR-0006: Catalog Sync Architecture (staged pipeline, change feeds, per-title refresh state)

**Status:** Proposed
**Date:** 2026-10-14
**Deciders:** @sharimpervez
**Related:** [Research: how other apps sync a catalog](../adhoc/catalog-sync-architecture-research.md); builds on ADR-001 (Celery + Scheduled Jobs) and ADR-0004; GitHub issues #64 (enrichment starves the worker) and PR #65.

---

## Context

The catalog (534k titles from TVDB, TVmaze and others) is filled and kept fresh by Celery Scheduled Jobs: discovery, enrichment, embeddings, reminders, gossip, re-ranking. These grew one fix at a time. Starting beat on 2026-10-12 showed the structure has real gaps. A research pass over Sonarr, Radarr, Jellyfin, Overseerr, Trakt's open repo, Yamtrack, MediaManager and Plex's provider example found that working catalogs share a few things we lack.

What is wrong today (code facts, checked against the repo and the live database):

1. **A failed provider call looks like "end of catalog".** Providers catch every error and return `[]`; the page walker treats an empty page as the end and marks the provider `fully_synced`. Live data shows rows that may be affected: `tvmaze / tv_show` is `fully_synced` after 42 pages and 458 items, and `omdb` is `fully_synced` with 0 items. (TVDB movie and TV rows look like genuine ends: 720 and 349 pages.) Whether TVmaze's 458 is a false end has not been proven.
2. **No per-title refresh record.** Enrichment picks "TV shows with no episode count, ordered by id", so the same failing rows come first. 168,040 TV shows still have no episodes and 42,519 titles have no runtime.
3. **One queue, one worker, no time limits, no lock.** One slow enrichment run held the only worker and delayed the every-minute reminder job (#64).
4. **Identity is enforced only in Python.** Titles have plain indexes, no unique rule on provider ids. Weak matching already merged distinct titles once (fixed in #62/#63).
5. **Refresh only fills blanks.** A show's status, ratings and rescheduled air dates never update.
6. **The full catalog is re-crawled** page by page. TVDB and TVmaze offer "what changed since" feeds that we do not use.
7. **Writes were one row at a time** over a 270 ms link (fixed for titles in #63, episodes in #65).
8. **One large service** does fetch, normalise, match, save and schedule.

Constraints: one developer, no budget, one small Oracle box (2 CPU, ~1 GB RAM), Postgres on a separate GCP e2-micro VM about 270 ms away, free tiers only. TMDb is off (commercial licence needed); Trakt forbids mirroring its catalog.

## Decision

**Adopt a staged sync pipeline on the existing Celery + Redis (research Option B), delivered in shippable phases, and evaluate moving the sync worker next to the database (Option C) after the batching work.**

### Shape of the target

- **Modules:** `providers` (fetch and normalise only, raise `ProviderError` on failure, never return `[]` for an error; small capabilities: changes-since, details, episodes, search), `identity` (resolver: match / create / conflict, pure, one place for all id and title rules), `store` (batched `INSERT ... ON CONFLICT`), `planner` (what is due now), `pipeline` (fetch → normalise → resolve → store for one chunk). Celery tasks stay thin.
- **Data model:**
  - `content_external_id (provider, kind, external_id)` with a database `PRIMARY KEY` / unique rule, one row per provider id. The old id columns on `content` were copies while pages and queries moved; migration `a1b6c4d8e2f7` (#89) dropped them, so this table is the only place provider ids live (episodes keep their own id columns).
  - Per-title refresh state on `content`: `last_refreshed_at`, `next_refresh_at`, `refresh_attempts`, `last_error`.
  - `sync_state` per (provider, stream): timestamp watermark, status, lease, last error (extends `discovery_state`).
- **Refresh tiers** (start values, tune with data): hot (tracked by a user, or something airing within 14 days) 6 h; warm (running shows, announced movies) 12 h to 1 day; cold (ended / released) 30 to 180 days; failed (3+ attempts) exponential backoff, capped at 7 days.
- **Incremental sync:** TVDB `/updates` and TVmaze `/updates/shows` with a stored watermark and overlap; tiers are the fallback when the gap is too large. TMDb feeds are out of scope while TMDb is disabled.
- **Jobs:** two queues. `fast` (reminders, cleanup) and `sync` (discovery, change feeds, enrichment, embeddings, and the paused gossip and re-ranking), each with its own worker, concurrency 1. Every periodic task gets `expires`, soft and hard time limits, a Redis lease so runs do not overlap, work in bounded chunks, idempotent saves, and per-title failure records instead of restarting a whole run.
- **Refresh** overwrites provider-owned fields, with a lock flag for hand-edited ones.

### Option C gate

Moving the sync worker to the database VM removes most of the round-trip cost, but that VM is an e2-micro (shared CPU, 1 GB RAM) already running Postgres; its spare memory and CPU are **not measured** (its SSH port is closed from outside). Decision rule: after batching (Phase 3) measure real sync time. Move the worker only if sync is still too slow **and** the VM has headroom for a ~100 MB worker without hurting Postgres. A worker on that VM also changes the source IP that providers see.

## Alternatives Considered

- **A. Harden in place** (failure handling, queues, locks, unique rules, no new tables). Days of work, immediate relief, but no change feeds, stale data never corrected, ids stay as columns. **Adopted as Phases 0 to 3 of B**, not as the end state.
- **C. Run the sync worker beside the database.** Removes the cause of slow writes, but depends on VM headroom and adds a second deploy target. **Deferred behind the gate above.**
- **Postgres-based queue** (Procrastinate and similar). Every poll and lock crosses the 270 ms link. **Rejected** (revisit only if the worker moves next to the database).
- **Kafka, Airflow, Kubernetes, search cluster.** No studied project uses them at this scale. **Rejected.**
- **Wikidata dumps (~130 GiB) or machine-learning matching.** Too heavy for the box; provider ids first. **Rejected.**

## Consequences

**Easier:** failures stop corrupting sync state; reminders cannot be starved; the database refuses duplicate ids; refresh effort goes to titles that change; each phase ships and is tested alone.

**Harder / new:** a data migration (id backfill and duplicate audit), new modules to learn, a second worker process (memory on the Oracle box must be measured), and a `ProviderError` contract every provider must follow.

**Phases** (details, tests and the problems each fixes are in the research file, section 6; they become the spec and tickets):

0. Failure is not "the end" (providers raise, walker stops, reset suspect `fully_synced` rows).
1. Queues, time limits, leases, `expires`, two workers.
2. Per-title refresh state and the tiered "due" query (replaces id-ordered enrichment).
3. Batch the remaining writes (PR #65 is part of this).
4. `content_external_id` table and the resolver.
5. Change feeds for TVDB and TVmaze with watermarks.
6. Bulk backfill and cleanup; correct stale docs (`ARCHITECTURE.md`, `DATA_FLOWS.md`, `PROVIDERS.md` still describe APScheduler).

**To revisit:** the Option C gate after Phase 3; tier lengths once real change-feed data exists; whether TMDb returns (it would add a third feed).

**Not verified:** Sonarr's metadata proxy source is closed; memory per Celery process on the Oracle box and spare capacity on the database VM are unmeasured; whether TVmaze's `fully_synced` state is a false end.
