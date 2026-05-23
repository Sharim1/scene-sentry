# Data Flows

Step-by-step traces for the most common operations. Use these to orient yourself before touching a feature.

---

## Browse and search movies

**Route:** `GET /movies?q=inception`

```
1. Request arrives at routes/content.py → movies_page()
2. Dependencies inject: db session (DbDep), current user (OptionalUserDep)
3. If q is set:
     ContentRepository(db).search("inception", content_type="movie", limit=40)
     → SELECT ... FROM content WHERE title ILIKE '%inception%' AND content_type='movie'
   Else:
     ContentRepository(db).get_paginated(content_type="movie", page=1)
4. If user is authenticated, fetch their library statuses for the returned content IDs:
     LibraryRepository(db).get_statuses_for_content_ids(user.id, content_ids)
     → dict of {content_id: WatchStatus}
5. Render templates/movies.html with movies + library_status dict
6. Template loops over movies; each card shows poster, title, rating, and a status badge
   if the content is in the user's library
```

---

## View content detail

**Route:** `GET /{content_id}`

```
1. routes/content.py → content_detail()
2. ContentRepository(db).get_by_id(content_id) — or 404
3. If TV show: EpisodeRepository(db).get_by_content(content_id)
4. If user authenticated:
     LibraryRepository(db).get_by_user_and_content(user.id, content_id)
     → the user's LibraryItem if it exists
5. Render templates/content_detail.html with content, episodes, library_item
```

---

## Add content to library

**Route:** `POST /library/item/{content_id}/add`

```
1. routes/library.py → add_to_library()
2. RequireAuthDep — 401 if not logged in
3. LibraryService(db).add(user.id, content_id, status="planned")
   a. Check for existing LibraryItem (idempotent — do nothing if already tracked)
   b. INSERT LibraryItem(user_id, content_id, status=PLANNED, created_at=now)
   c. Invalidate user's rankings:
        RankingRepository(db).mark_stale_for_user(user.id)
   d. db.commit()
4. Redirect to /library or return HTMX partial response
```

---

## Update library status or rating

**Route:** `POST /library/item/{item_id}/update`

```
1. routes/library.py → update_library_item()
2. RequireAuthDep
3. LibraryService(db).update(item_id, user.id, status=..., rating=...)
   a. Fetch LibraryItem — 404 if not found, 403 if not owned by user
   b. Apply changes (status, rating, notes, progress, timestamps)
   c. If status or rating changed:
        RankingRepository(db).mark_stale_for_user(user.id)
   d. db.commit()
4. Return updated partial or redirect
```

---

## Gossip feed

**Route:** `GET /gossip`

```
1. routes/gossip.py → gossip_feed()
2. OptionalUserDep
3. If user authenticated and has library items:
     tag filter from query param (optional)
     GossipRepository(db).get_feed(tag=tag, limit=50)
   Else:
     GossipRepository(db).get_feed(limit=50)  — unfiltered
4. Render templates/gossip/feed.html
```

**Route:** `POST /gossip/refresh` (triggers on-demand scrape)

```
1. RequireAuthDep
2. LibraryRepository(db).get_all_tracked_titles(user.id)
3. task_manager.start_task("gossip", user.id)
   → GossipService(db).scrape_latest(tracked_titles)
     → GossipScraperAgent.scrape_gossip(titles)
       → for each title: tavily.search(f"{title} entertainment news")
       → parse results → classify GossipTag → deduplicate by source_url
       → INSERT Gossip rows
4. SSE stream reports progress back to the browser
```

---

## On-demand ranking (Task)

**Route:** `POST /api/tasks/rerank`

```
1. RequireAuthDep
2. task_manager.start_task("rerank", user.id)
3. In background thread:
     RankingService(db).run_for_user(user.id)
       → ContentRankingGraph.run(user.id)
         → build_taste_profile: aggregate genres/ratings from user's LibraryItems
         → select_candidates: SQL for unranked/stale Content in top genres
         → batch_score: send batches of 20 to Gemini with taste profile
         → write_rankings: upsert UserContentRank rows
         → validate_quality: check diversity; loop if insufficient
4. SSE stream (GET /api/tasks/{task_id}/stream) reports node-by-node progress
```

---

## Scheduled content discovery (background)

Triggered by APScheduler every 6 hours:

```
1. scheduler.py → content_discovery_task()
2. ContentDiscoveryService(db).run_scheduled_sync()
3. providers = get_active_providers()  # from registry.py
4. For each provider:
   a. Load DiscoveryState for (provider.name, content_type)
   b. Call provider.discover_movies(page=state.last_page + 1) (and tv_shows)
   c. Collect list[NormalizedContent]
5. Deduplicate in memory (merge by dedup_key, first-provider-wins)
6. ContentRepository(db).upsert(items)
   a. For each item: try to match by external ID, then dedup_key
   b. If match: fill blank fields only (no overwrites)
   c. If no match: INSERT new Content row
7. Advance DiscoveryState.last_page += 1
   If provider returned 0 items: set fully_synced=True, reset last_page=0
8. db.commit()
```

---

## Scheduled content enrichment (background)

Triggered every 15 minutes:

```
1. ContentDiscoveryService(db).enrich_sparse_content(limit=50)
2. ContentRepository(db).get_sparse(limit=50)
   → SELECT content WHERE poster_url IS NULL OR runtime_minutes IS NULL ...
3. For each sparse Content row:
   a. Find the best provider that has an ID for this content
   b. provider.get_details(external_id)  → NormalizedContent
   c. provider.get_episodes(external_id) → list[dict]  (TV shows only)
   d. Update Content row with newly fetched fields
   e. Upsert Episode rows
4. db.commit()
```

---

## Clerk auth flow

```
Browser → Clerk-hosted login page → Clerk issues JWT
Browser sends JWT as Authorization header or cookie on each request
  ↓
ClerkAuthMiddleware (app/middleware/clerk.py)
  1. Extract JWT from request headers/cookies
  2. Verify signature using Clerk public key
  3. Extract clerk_user_id from token claims
  4. Look up User in local DB by clerk_user_id
     If not found: call Clerk API to fetch user details, INSERT User row
  5. Set request.state.user and request.state.clerk_user_id
  ↓
Route handler — reads user from request.state via OptionalUserDep / RequireAuthDep
```

---

## Reminder dispatch (background)

Triggered every 60 minutes:

```
1. ReminderService(db).process_due_reminders()
2. ReminderRepository(db).get_due(now=datetime.utcnow())
   → SELECT reminders WHERE remind_at <= now AND is_sent = false
3. For each due reminder:
   a. Create Notification for the user
   b. If user.notification_email: send email via EmailService
   c. Set reminder.is_sent = True
4. db.commit()
```
