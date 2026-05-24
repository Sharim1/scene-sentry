# Scene Sentry

An AI-powered cinema intelligence platform that helps users track, discover, and get personalized rankings for entertainment media.

## Language

### Catalog & Content

**Content**:
A movie or TV show that Scene Sentry knows about. The canonical entity ingested from external providers and stored in the catalog.
_Avoid_: Title, media, item (when referring to a catalog entry — "item" is reserved for **Library Item**)

**Catalog**:
The global pool of all **Content** in the system, regardless of whether any user is tracking it. Populated by **Providers** via discovery and enrichment. Every user sees the same catalog.
_Avoid_: Database, content list, feed

**Episode**:
A single installment of a TV show, identified by season and episode number. Belongs to exactly one **Content** (of type TV show). Enriched from **Providers**. Multi-part movies (e.g. Dune Part 1, Part 2) are separate **Content** entries, not episodes.
_Avoid_: Part, chapter, segment

### User Library

**Library**:
A single user's personal collection of **Library Items** — the subset of the **Catalog** they have chosen to track. Drives personalized **Gossip** queries and **Ranking**.
_Avoid_: Watchlist, collection, shelf

**Library Item**:
A user's tracked entry for a piece of **Content**. Carries a **Watch Status**, optional rating, progress, and notes. One user can have at most one **Library Item** per **Content**.
_Avoid_: Bookmark, list entry, watchlist item

**Watch Status**:
The tracking state of a **Library Item**: `watching`, `planned`, `completed`, `dropped`, or `maybe`.
_Avoid_: Tracking status, progress status

### Ingestion

**Provider**:
An external API that supplies **Content** to the **Catalog** — TVMaze, TVDB, OMDb, or TMDb. Each provider implements a common interface for discovery, search, and episode data. Note: the `Content.source` column currently stores the provider name; a rename to `Content.provider` is tracked in SCE-5.
_Avoid_: Source (when referring to a content provider — "source" is reserved for the publication origin of **Gossip**)

**Discovery**:
The process of pulling new **Content** from a **Provider** into the **Catalog**. Paginated, tracked via per-provider sync state. Runs on a schedule (default: every 6 hours).
_Avoid_: Import, ingestion, sync (when specifically meaning first-time catalog population)

**Enrichment**:
The process of backfilling missing details (episodes, runtime, images) on **Content** that is already in the **Catalog** but has sparse data. Runs on a separate, more frequent schedule (default: every 15 minutes).
_Avoid_: Backfill, update (when specifically meaning filling gaps on existing catalog entries)

**Dedup Key**:
A normalized string (`lowercase(title) + year + content_type`) used as a fallback to match **Content** across **Providers** when no shared external ID (IMDb, TMDb, TVDB, TVMaze) exists. Deduplication runs in two layers: first in-memory across a provider batch, then against the database at persistence. The result is always one **Content** row per real-world movie or show, with external IDs and fields merged from all matching providers. First provider to supply a field wins; later providers only fill blanks.
_Avoid_: Match key, content key

### Intelligence

**Gossip**:
A scraped news headline from an entertainment trade publication (Variety, Deadline, etc.), fetched via Tavily. Stores a preview and links out to the original article — Scene Sentry does not host full articles. Optionally linked to a specific **Content**; unlinked gossip covers general industry news. A global resource — fetched by a scheduled job using titles tracked across all users, not per-user. Intentionally playful branding.
_Avoid_: News, article, post

**Ranking**:
A personalized relevance score (0–100) for a piece of **Content** against a user's **Taste Profile**, with an LLM-generated reasoning string. Stored as `UserContentRank`. Stale rankings are invalidated when **Library Item** status or rating changes.
_Avoid_: Recommendation, suggestion (the dead `Recommendation` model is legacy — see SCE-6)

**Taste Profile**:
An aggregate summary of a user's preferences derived from their **Library** — genre distribution, rating patterns, content type ratios. Built without an LLM. Used as input to the **Ranking** pipeline so the LLM can score **Content** against the user's actual behavior.
_Avoid_: Preference, user profile (when referring specifically to the ranking input)

### Notifications & Tasks

**Reminder**:
A user-created scheduled alert tied to a specific date — "remind me when this premieres." Has a type (`watch`, `next_episode`, `premiere`, `finale`, `release`) and optionally links to a **Library Item** or **Content**. When due, generates a **Notification**.
_Avoid_: Alert, timer, scheduled notification

**Notification**:
A system-wide message delivered to a user in-app (with optional email). Can originate from a due **Reminder**, but also from other sources — subscription offers, platform announcements, feature updates. Has read/unread state. Not scoped to reminders alone.
_Avoid_: Alert, message (when referring to the in-app notification system)

**Scheduled Job**:
An automated background process run by Celery Beat on a timer. Covers gossip scraping (global, across all tracked titles), content re-ranking (per-user, iterates all users), discovery, enrichment, reminders, and cleanup. Users have no manual trigger — the system handles all refresh cadences.
_Avoid_: Task (removed concept — there are no user-triggered background jobs)

## Example dialogue

> **Dev**: A user reported that after they rated a movie, their recommendations didn't update.
>
> **Domain expert**: You mean their **Rankings** didn't update — we don't have recommendations. When a user changes a rating on a **Library Item**, that should invalidate their existing **Rankings** so the next reranking run scores fresh. Did the invalidation fire?
>
> **Dev**: I think so. The scheduled job ran but nothing changed.
>
> **Domain expert**: The **Scheduled Job** for re-ranking runs on a timer and reranks *all* users. The pipeline builds a **Taste Profile** from their **Library**, selects candidates from the **Catalog**, and batch-scores them. If the rating change didn't alter the **Taste Profile** enough, the scores might genuinely stay the same — even after the next run.
>
> **Dev**: Got it. Also, some of the Content they rated doesn't have a poster. Should I backfill that?
>
> **Domain expert**: That's **Enrichment** — it runs every 15 minutes and fills gaps like missing posters. If the **Provider** that originally discovered the **Content** didn't have a poster, enrichment tries other providers. Check whether the **Content** has IDs from multiple providers or just one — if just one, enrichment may not have found a better source yet.
