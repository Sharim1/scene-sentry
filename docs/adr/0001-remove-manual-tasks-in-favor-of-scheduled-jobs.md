# Remove manual Tasks in favor of Scheduled Jobs

Both gossip scraping and content re-ranking were available as user-triggered Tasks (with SSE progress) and as automated Celery Beat jobs. We decided to remove the manual Task system entirely and rely solely on scheduled jobs. Gossip is a global resource — every user sees the same feed, so per-user triggering produced duplicate work with no differentiated output. Re-ranking is per-user but the scheduled job already iterates all users; no consumer recommendation engine (Netflix, Spotify, YouTube) exposes a manual "refresh" button, and doing so leaks infrastructure into the UX.

## Considered Options

- **Keep manual Tasks for re-ranking only** (gossip is global, but re-ranking is personal). Rejected because even personal re-ranking doesn't need a manual trigger — the scheduled cadence is sufficient, and event-driven re-ranking (trigger on Library changes) is a better future path than a button.
- **Global-scoped manual refresh** (single admin-level trigger instead of per-user). Rejected as unnecessary complexity — the scheduled interval already covers this.
