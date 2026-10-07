# Database Models

All models live in `app/models/`. SQLAlchemy 2.0 ORM with declarative base. The database is PostgreSQL in production and SQLite for development/testing.

---

## Content

**`app/models/content.py`** — the catalog entry for a movie or TV show.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `title` | String | Required |
| `content_type` | String | `"movie"` or `"tv_show"` |
| `year` | Integer | Release / premiere year |
| `description` | Text | |
| `poster_url` | String | |
| `backdrop_url` | String | |
| `trailer_url` | String | |
| `genres` | JSON | List of genre strings |
| `rating` | Float | Aggregated from providers |
| `runtime_minutes` | Integer | |
| `status` | String | `"Running"`, `"Ended"`, etc. |
| `language` | String | ISO 639-1 |
| `imdb_id` | String | For dedup and external links |
| `tmdb_id` | String | |
| `tvdb_id` | String | |
| `tvmaze_id` | String | |
| `source` | String | Provider that first ingested this row |
| `dedup_key` | String | `lowercase(title)_year_content_type` |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

**Relationships:** `episodes` (one-to-many `Episode`), `library_items` (one-to-many `LibraryItem`), `gossip` (one-to-many `Gossip`).

---

## Episode

**`app/models/episode.py`** — a single episode of a TV show.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `content_id` | FK → Content | The parent TV show |
| `season_number` | Integer | |
| `episode_number` | Integer | |
| `title` | String | |
| `description` | Text | |
| `air_date` | Date | |
| `runtime_minutes` | Integer | |
| `tvmaze_id` | String | |
| `tvdb_id` | String | |

---

## User

**`app/models/user.py`** — a registered user, synced from Clerk or created locally.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `clerk_user_id` | String | Nullable — None for local auth users |
| `email` | String | Unique |
| `username` | String | |
| `password_hash` | String | Nullable — None for Clerk-only users |
| `timezone` | String | IANA tz name, e.g. `"America/New_York"` |
| `notification_email` | Boolean | Opt-in for email notifications |
| `search_api` | String | `"tavily"` or `"brightdata"` |
| `created_at` | DateTime | |

**Relationships:** `library_items`, `notifications`, `reminders`, `rankings`.

---

## LibraryItem

**`app/models/library.py`** — a user's tracked entry for a piece of content.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK → User | |
| `content_id` | FK → Content | Unique together with `user_id` |
| `status` | Enum (WatchStatus) | See below |
| `rating` | Integer | 1–10, nullable |
| `notes` | Text | |
| `current_season` | Integer | TV show progress |
| `current_episode` | Integer | TV show progress |
| `started_at` | DateTime | |
| `finished_at` | DateTime | |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

**WatchStatus enum:** `watching`, `planned`, `completed`, `dropped`, `maybe`

One user can have at most one `LibraryItem` per `Content` (enforced by unique constraint).

---

## Gossip

**`app/models/gossip.py`** — a scraped entertainment news headline.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `headline` | String | |
| `snippet` | Text | Preview text |
| `source_url` | String | Unique — prevents duplicate scrapes |
| `source_name` | String | Publication name (Variety, Deadline, etc.) |
| `image_url` | String | |
| `tag` | Enum (GossipTag) | See below |
| `confidence_score` | Float | Tag classification confidence |
| `sentiment` | String | |
| `content_id` | FK → Content | Nullable — linked to a specific title if known |
| `created_at` | DateTime | |

**GossipTag enum:** `CASTING`, `PRODUCTION`, `RUMOR`, `RENEWAL`, `CANCELLATION`, `RELEASE`, `AWARD`, `GENERAL`

---

## Notification

**`app/models/notification.py`** — an in-app alert delivered to a user.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK → User | |
| `title` | String | |
| `body` | Text | |
| `is_read` | Boolean | Default False |
| `created_at` | DateTime | |

---

## Reminder

**`app/models/reminder.py`** — a user-created scheduled alert.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK → User | |
| `content_id` | FK → Content | Nullable |
| `library_item_id` | FK → LibraryItem | Nullable |
| `reminder_type` | Enum (ReminderType) | See below |
| `remind_at` | DateTime | When to fire |
| `is_sent` | Boolean | |
| `custom_message` | Text | |
| `created_at` | DateTime | |

**ReminderType enum:** `watch`, `next_episode`, `premiere`, `finale`, `release`, `custom`

When `remind_at` is reached, `ReminderService` creates a `Notification` for the user and sets `is_sent = True`.

---

## UserContentRank (Ranking)

**`app/models/ranking.py`** — a personalized relevance score for a piece of content.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK → User | |
| `content_id` | FK → Content | Unique together with `user_id` |
| `score` | Integer | 0–100 |
| `reasoning` | Text | LLM-generated explanation |
| `is_stale` | Boolean | True after library change; re-ranked next run |
| `scored_at` | DateTime | |

Rankings are invalidated (set `is_stale = True`) whenever the user changes a Library Item's status or rating.

---

## DiscoveryState

**`app/models/discovery_state.py`** — pagination cursor for each provider/content-type pair.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `provider_name` | String | e.g. `"tmdb"` |
| `content_type` | String | `"movie"` or `"tv_show"` |
| `last_page` | Integer | Last successfully fetched page |
| `total_items_fetched` | Integer | |
| `fully_synced` | Boolean | True when provider returned 0 items |
| `last_run_at` | DateTime | |

Unique constraint on `(provider_name, content_type)`.

---

## Recommendation (legacy)

**`app/models/recommendation.py`** — unused. Will be removed (SCE-6). Do not add code that references this model.
