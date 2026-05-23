# Content Providers

Providers are how Scene Sentry gets content into the catalog. Each provider wraps a single external API, normalizes its output into a common shape, and is swappable without touching the rest of the system.

---

## The provider abstraction

**`app/services/providers/base.py`** defines two things:

### `ContentProvider` (ABC)

Every provider implements this interface:

```python
class ContentProvider(ABC):
    @abstractmethod
    def discover_movies(self, page: int = 1) -> list[NormalizedContent]: ...

    @abstractmethod
    def discover_tv_shows(self, page: int = 1) -> list[NormalizedContent]: ...

    @abstractmethod
    def search(self, query: str, content_type: str) -> list[NormalizedContent]: ...

    @abstractmethod
    def get_details(self, external_id: str) -> NormalizedContent | None: ...

    @abstractmethod
    def get_episodes(self, external_id: str) -> list[dict]: ...

    # Optional — not all providers implement this
    def get_upcoming(self) -> list[NormalizedContent]: ...
```

### `NormalizedContent` (dataclass / DTO)

The platform-agnostic object that all providers return:

```python
@dataclass
class NormalizedContent:
    title: str
    content_type: str           # "movie" or "tv_show"
    year: int | None
    description: str | None
    poster_url: str | None
    backdrop_url: str | None
    trailer_url: str | None
    genres: list[str]
    rating: float | None
    runtime_minutes: int | None
    status: str | None          # "Ended", "Running", etc.
    language: str | None
    # External IDs — used for deduplication
    imdb_id: str | None
    tmdb_id: str | None
    tvdb_id: str | None
    tvmaze_id: str | None
    # Computed for dedup fallback
    dedup_key: str              # f"{title.lower()}_{year}_{content_type}"
    source: str                 # provider name, e.g. "tmdb"
```

---

## Active providers

Which providers run is controlled by feature flags and API key availability in `app/config.py`. `get_active_providers()` in `app/services/providers/registry.py` returns only enabled + configured providers.

| Provider | File | Content type | API key required | Notes |
|---|---|---|---|---|
| **TVMaze** | `tvmaze_provider.py` | TV shows only | No (public) | Rate-limited: 20 req/10s |
| **TMDb** | `tmdb_provider.py` | Movies + TV | Yes (`TMDB_API_KEY`) | Primary for trending/search |
| **TVDB** | `tvdb_provider.py` | TV shows | Yes (`TVDB_API_KEY`) | Best for episode-level data |
| **OMDb** | `omdb_provider.py` | Movies | Yes (`OMDB_API_KEY`) | IMDb ratings, metadata |

---

## How discovery works

`ContentDiscoveryService` (`app/services/content_discovery.py`) orchestrates the full ingestion loop:

1. Call `get_active_providers()` to get all enabled providers.
2. For each provider + content type pair, load the `DiscoveryState` (pagination cursor).
3. Call `provider.discover_movies(page=state.last_page + 1)` or `discover_tv_shows(...)`.
4. Collect all returned `NormalizedContent` items.
5. Deduplicate (see below).
6. Upsert into the `Content` table via `ContentRepository.upsert()`.
7. Advance the `DiscoveryState` cursor. If the provider returned zero items, mark `fully_synced = True` and reset to page 1 (refresh mode).

Enrichment is a separate pass — it targets existing `Content` rows with sparse data (missing poster, runtime, episodes) and calls `get_details()` / `get_episodes()` on the appropriate provider.

---

## Deduplication

The same movie or show often appears in multiple providers. Dedup runs in two layers:

**Layer 1 — in-memory batch dedup**
Before writing to the database, the current batch of `NormalizedContent` items is deduplicated among themselves. Items with the same `dedup_key` are merged, with the first provider's value winning for each field.

**Layer 2 — database dedup (upsert)**
`ContentRepository.upsert()` checks existing `Content` rows in priority order:
1. Match by any shared external ID (`imdb_id`, `tmdb_id`, `tvdb_id`, `tvmaze_id`).
2. Fall back to `dedup_key` (`lowercase(title) + year + content_type`).

If a match is found, only blank fields are filled in — existing data is not overwritten. If no match, a new `Content` row is inserted.

The result: one `Content` row per real-world movie or show, with external IDs and metadata merged from all matching providers.

---

## Adding a new provider

1. Create `app/services/providers/your_provider.py`.
2. Implement `ContentProvider`:
   - `discover_movies()` and `discover_tv_shows()` for catalog population.
   - `search()` for on-demand user search.
   - `get_details()` for enrichment.
   - `get_episodes()` if the API has episode data.
3. Map the API response to `NormalizedContent` — set `source = "your_provider_name"` and populate as many external IDs as possible (they're what powers dedup).
4. Add a feature flag to `app/config.py` (e.g. `your_provider_enabled: bool = False`) and an optional API key field.
5. Register the provider in `app/services/providers/registry.py`:
   ```python
   if settings.your_provider_enabled and settings.your_provider_api_key:
       providers.append(YourProvider(settings.your_provider_api_key))
   ```
6. Done. Discovery, enrichment, and search will pick it up automatically.

---

## DiscoveryState

`app/models/discovery_state.py` — one row per `(provider_name, content_type)` pair.

| Column | Purpose |
|---|---|
| `provider_name` | e.g. `"tmdb"` |
| `content_type` | `"movie"` or `"tv_show"` |
| `last_page` | Last successfully fetched page number |
| `total_items_fetched` | Running count |
| `fully_synced` | True when provider returned 0 items (end of catalog) |
| `last_run_at` | Timestamp of last sync attempt |

Once `fully_synced = True`, the next discovery run resets `last_page` to 0 and picks up any newly added content from the provider's beginning.
