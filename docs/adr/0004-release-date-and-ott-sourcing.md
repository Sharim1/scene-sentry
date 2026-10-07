# ADR-0004: Release-Date & OTT Platform Sourcing and Auto-Reminders

**Status:** Accepted
**Date:** 2026-06-20
**Deciders:** @sharimpervez
**Related:** PRD [Personalized Discovery & Recommendations](../prd/personalized-discovery-and-recommendations.md); builds on ADR-001 (Celery + Scheduled Jobs); sequence after SCE-5.

---

## Context

Users want a **Reminder** created automatically when a tracked title gets a release date, and they want to know *where* (theater vs which OTT) and *when*. Today `Content` has `premiere_date`, `next_episode_date`, and a free-text `release_date` string, plus `network` (TV). The **Reminder** model already supports `release` and `premiere` types. What's missing: a structured notion of **release type** (theatrical vs streaming) and **which platform/OTT**, and the automation that turns release data into Reminders.

## Decision

**Add structured release fields to `Content`, populate them via a Scheduled Job, and auto-create Reminders for tracked titles — never via a user-triggered task.**

- **`Content` additions:** `release_type` (`theatrical` | `streaming` | `physical` | `tbd`), `platform` (e.g. "Netflix", "Prime Video", or theatrical), and structured release date(s). `network` (existing) covers linear-TV; `platform` covers OTT/theatrical.
- **Sourcing:** prefer **Provider** release data where available; fall back to the **Discovery agent** (ADR-0002) scraping/searching release windows via the existing **Gossip**/Tavily plumbing. Scraped release data is treated as best-effort and flagged as such.
- **Auto-Reminder Scheduled Job:** for each tracked **Library Item** whose **Content** has a known future release date, create the corresponding `release`/`premiere` Reminder if one doesn't already exist (idempotent). Runs on Celery Beat alongside the existing reminder job.

## Alternatives Considered

- **Manual reminders only (status quo).** Lowest effort, but misses the "don't make me track dates" value and the daily-habit goal. **Rejected.**
- **A dedicated paid release-data/OTT-availability API (JustWatch-style).** Best accuracy and true "where to watch," but a paid dependency and licensing scope. **Deferred** — this is the natural v2 upgrade once the structured fields exist; the schema is designed so a better source can backfill the same fields later.
- **LLM/agent as the sole source of release dates.** Flexible, but scraping reliability is a real risk; treated as a *fallback* behind Provider data, with results flagged best-effort. **Partially adopted** (fallback only).

## Consequences

**Easier:** users get automatic, idempotent Reminders and can see where/when a title lands; the structured fields are reusable by a future paid availability source.

**Harder / new:** scraped release data can be wrong or stale — must be flagged and overridable; new `Content` fields mean migrations that **must land after SCE-5**; release "where to watch" is region-dependent and we are not solving full regional availability at launch.

**To revisit:** adding a paid availability provider (the real "where can I watch this" — current #1 v2 candidate); regional/locale handling; how aggressively the Discovery agent should scrape vs wait for Provider data.
