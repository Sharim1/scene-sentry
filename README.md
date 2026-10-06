# Scene Sentry

AI-powered cinema intelligence platform. Get personalized content rankings, track your watchlist, and stay updated with the latest entertainment news.

## Features

- **AI-Powered Re-ranking**: LangGraph-orchestrated agent that periodically scores and ranks content based on your taste profile
- **Entertainment Gossip**: Real-time aggregation of news from Variety, Deadline, Hollywood Reporter, and more — with external read-through links
- **TMDB/TVDB Integration**: Movies and TV shows sourced from official APIs for clean, legal data
- **Reminders**: Configure reminders for upcoming shows, movies, and premieres
- **Library Management**: Track what you're watching, planning to watch, or have completed

## Tech Stack

- **Backend**: FastAPI + Python 3.11+
- **Database**: SQLAlchemy ORM + Alembic migrations (SQLite or PostgreSQL; pgvector required on Postgres for embeddings)
- **Background Tasks**: Celery + Redis (periodic jobs via Celery Beat)
- **AI**: LangChain + LangGraph + Google Gemini (content re-ranking agent)
- **Content APIs**: Multi-provider (TVMaze, TVDB, OMDb, TMDb) with deduplication
- **Search**: Tavily API for gossip aggregation
- **Frontend**: Jinja2 templates + Tailwind CSS + Alpine.js
- **Auth**: Session-based (Clerk integration ready)

## Architecture

```
app/
  routes/           # Thin HTTP handlers
  services/         # Business logic layer
    providers/      # Content provider abstraction (TVMaze, TVDB, OMDb, TMDb)
  repositories/     # Database access wrappers
  models/           # SQLAlchemy models
  agents/           # LangGraph re-ranking agent
  middleware/       # Auth middleware
  tasks/            # Celery periodic tasks
```

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Node.js 18+ and npm (for the Tailwind/JS build step)
- Redis (for background tasks and on-demand task state)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd scene-sentry
```

2. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e .
# Or with uv:
uv sync
```

4. Build frontend assets (Tailwind CSS + bundled JS):
```bash
npm install
npm run build      # outputs static/dist/tailwind.css + static/dist/app.js
# During development, run `npm run dev` in a separate terminal to rebuild on change
```

5. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys and DATABASE_URL (see Database below)
```

6. Start backing services:
```bash
# Postgres (pgvector) + Redis — recommended for full feature parity
docker compose up -d postgres redis

# Or Redis only if you use SQLite in .env:
docker run -d -p 6379:6379 redis:7-alpine
```

7. Run the application (three terminals):
```bash
# Terminal 1 — Web server
fastapi dev

# Terminal 2 — Celery worker
uv run celery -A app.celery_app worker --pool=solo --loglevel=info

# Terminal 3 — Celery beat (periodic tasks)
uv run celery -A app.celery_app beat --loglevel=info
```

8. Open http://localhost:8000 in your browser

### Database

The app runs Alembic migrations on startup. Choose one setup:

| Setup | `DATABASE_URL` | Embeddings / similarity |
|-------|----------------|-------------------------|
| **Docker Postgres (recommended)** | `postgresql://scenesentry:scenesentry@localhost:5433/scenesentry` | Full (pgvector included) |
| **SQLite (quickest)** | `sqlite:///scenesentry.db` | Columns only — no vector search |
| **Local Homebrew Postgres** | your existing URL | Requires `brew install pgvector` for your Postgres version |

```bash
# Recommended: pgvector-enabled Postgres (port 5433 avoids clashing with Homebrew Postgres on 5432)
docker compose up -d postgres
```

If startup fails with `could not open extension control file ... vector.control`, you are pointing at Postgres **without** pgvector — switch to the Docker URL above or SQLite.

### Content Provider API Keys

At least one content provider should be enabled for the app to show movies/TV data.
Enable them via the corresponding feature flags in `.env`:

| Key | Source | Get it from | Feature flag |
|---|---|---|---|
| `TVMAZE_API_KEY` | TVMaze (TV shows) | [TVMaze Premium](https://www.tvmaze.com/premium) | `TVMAZE_ENABLED=true` (default) |
| `TVDB_API_KEY` | TheTVDB (movies + TV) | [TheTVDB](https://thetvdb.com/api-information) | `TVDB_ENABLED=true` (default) |
| `OMDB_API_KEY` | OMDb (movies + TV) | [OMDb](https://www.omdbapi.com/apikey.aspx) | `OMDB_ENABLED=true` (default) |
| `TMDB_API_KEY` | TMDb (movies + TV) | [TMDb](https://www.themoviedb.org/settings/api) | `TMDB_ENABLED=false` (requires commercial license) |

TVMaze public API works without a key; the key unlocks premium/user endpoints.
OMDb free tier allows 1,000 requests/day.
TMDb is disabled by default — a commercial API key is needed for revenue-generating projects.

### Other API Keys

- **TAVILY_API_KEY**: Get from [Tavily](https://tavily.com/) (for gossip scraping)
- **GEMINI_API_KEY**: Get from [Google AI Studio](https://aistudio.google.com/) (for AI re-ranking)

### Clerk Authentication (optional)

When using [Clerk](https://clerk.com/) for sign-in, set at least:

- **CLERK_SECRET_KEY**: Secret key from the Clerk dashboard
- **CLERK_PUBLISHABLE_KEY**: Publishable key
- **CLERK_ISSUER**: Frontend API URL (e.g. `https://your-instance.clerk.accounts.dev`)

## Development

### Running Tests
```bash
pytest
```

### Database Migrations
Schema is managed by Alembic (`alembic/versions/`). Migrations run automatically on app startup via `init_db()`.

```bash
# Manual migration commands (optional)
uv run alembic upgrade head
uv run alembic downgrade -1
```

### Tailwind CSS
Tailwind is loaded via CDN in development. For production, you can compile:
```bash
npx tailwindcss -i ./static/css/input.css -o ./static/css/app.css --minify
```

## License

MIT License
