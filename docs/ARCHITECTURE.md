# Scene Sentry Architecture Documentation

## Overview

**Scene Sentry** is an AI-powered cinema intelligence platform built with FastAPI. It aggregates movie and TV show data from TMDB/TVDB APIs, curates entertainment gossip via Tavily, and uses a LangGraph-based re-ranking agent to deliver personalised content recommendations.

### Core Features

- **TMDB/TVDB Integration**: Movies and TV shows sourced from official APIs
- **AI Content Re-ranking**: LangGraph agent that periodically scores and ranks content based on user taste
- **Entertainment Gossip**: Aggregated headlines with external read-through links
- **Reminders**: Configure alerts for upcoming shows, premieres, and movies
- **Library Management**: Track watching, planned, completed, and dropped content

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Client Browser                       │
│      (Jinja2 Templates + Tailwind CSS + Alpine.js)      │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/HTTPS
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI Application                      │
│  Middleware: ClerkAuth → Session                         │
│  Routes → Services → Repositories → Database            │
└───┬──────────────┬──────────────┬───────────────────────┘
    │              │              │
┌───▼───┐   ┌─────▼─────┐   ┌───▼──────────┐
│  DB   │   │ LangGraph │   │  Background  │
│SQLite/│   │ Re-ranking│   │  Scheduler   │
│Postgres│  │  Agent    │   │ (APScheduler)│
└───────┘   └─────┬─────┘   └──────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
┌───▼───┐  ┌─────▼─────┐  ┌───▼──────┐
│ TMDB  │  │  Tavily   │  │  Gemini  │
│ TVDB  │  │ (gossip)  │  │  (LLM)   │
└───────┘  └───────────┘  └──────────┘
```

---

## Application Structure

```
scene-sentry/
├── app/
│   ├── main.py                     # FastAPI entry point
│   ├── config.py                   # Pydantic Settings
│   ├── database.py                 # SQLAlchemy engine & sessions
│   │
│   ├── routes/                     # Thin HTTP handlers
│   │   ├── auth.py                 # Login / Register / Clerk
│   │   ├── dashboard.py            # Dashboard
│   │   ├── content.py              # Movies & TV Shows
│   │   ├── gossip.py               # Gossip feed
│   │   ├── library.py              # User library CRUD
│   │   ├── reminders.py            # Reminders CRUD + calendar
│   │   └── api.py                  # JSON API + task management
│   │
│   ├── services/                   # Business logic layer
│   │   ├── content_service.py      # TMDb API client
│   │   ├── tvdb_service.py         # TVDB API client
│   │   ├── content_discovery.py    # Discover & persist content
│   │   ├── gossip_service.py       # Gossip business logic
│   │   ├── reminder_service.py     # Reminder business logic
│   │   ├── ranking_service.py      # Re-ranking orchestration
│   │   └── task_manager.py         # Background task management + SSE
│   │
│   ├── repositories/               # Database access wrappers
│   │   ├── content_repo.py
│   │   ├── gossip_repo.py
│   │   ├── reminder_repo.py
│   │   ├── library_repo.py
│   │   └── ranking_repo.py
│   │
│   ├── models/                     # SQLAlchemy models
│   │   ├── user.py
│   │   ├── content.py
│   │   ├── library.py
│   │   ├── gossip.py
│   │   ├── reminder.py
│   │   └── ranking.py              # UserContentRank
│   │
│   ├── agents/                     # LangGraph agents
│   │   ├── graph.py                # ContentRankingGraph
│   │   └── gossip_agent.py         # Gossip headline scraper
│   │
│   ├── middleware/
│   │   └── clerk.py                # Clerk JWT middleware
│   │
│   └── tasks/
│       └── scheduler.py            # APScheduler jobs
│
├── templates/                      # Jinja2 templates
├── static/                         # CSS, JS, images
├── pyproject.toml
└── README.md
```

---

## Layered Architecture

```
Router  →  Service  →  Repository  →  Database
  │            │            │
  │            │            └─ Pure CRUD, no business logic
  │            └─ Orchestrates repos, external APIs, agents
  └─ HTTP concerns only: parse input, call service, return response
```

### Router Layer (`routes/`)
- Parse request parameters and forms
- Call the appropriate service
- Return HTML templates or JSON responses
- No direct database queries

### Service Layer (`services/`)
- All business logic lives here
- Orchestrates repositories, external API clients, and agents
- Transaction boundaries managed at this level

### Repository Layer (`repositories/`)
- Thin wrappers around SQLAlchemy queries
- One repository per model
- No business logic — only CRUD and query composition

---

## AI Re-ranking Agent

The LangGraph-based `ContentRankingGraph` in `agents/graph.py` runs a 5-node pipeline:

```
Entry → build_taste_profile → select_candidates → batch_score → write_rankings → validate_quality
                                     ↑                                                    │
                                     └────────────── (if insufficient diversity) ──────────┘
```

| Node | Uses LLM? | Purpose |
|---|---|---|
| `build_taste_profile` | No | Computes genre frequencies, avg ratings, type ratios from user's library |
| `select_candidates` | No | SQL query for unranked/stale content matching top genres |
| `batch_score` | **Yes (Gemini)** | Sends taste profile + candidates in batches of 20 for 0-100 scoring |
| `write_rankings` | No | Upserts scores into `UserContentRank` via repository |
| `validate_quality` | No | Checks diversity and count; loops back if insufficient |

Triggered by: scheduler (every N hours) and library events (rating, status change).

---

## Background Tasks

| Task | Interval | Function |
|---|---|---|
| Gossip Scraping | 30 min | Searches Tavily for entertainment news, stores headline + preview |
| Content Re-ranking | 2 hours | Runs `ContentRankingGraph` for each user |
| Reminders | 60 min | Marks due reminders as sent |
| Cleanup | 24 hours | Removes old gossip and sent reminders |

---

## Database Schema (Key Models)

- **User**: Account info, preferred genres, Clerk integration
- **Content**: Movies/TV shows from TMDB/TVDB (title, poster, rating, genres, tmdb_id)
- **LibraryItem**: User's tracked content with status (watching/planned/completed/dropped/maybe)
- **UserContentRank**: Per-user relevance scores (0-100) with reasoning text
- **Gossip**: Entertainment news headlines with preview text and external source links
- **Reminder**: User-configured alerts with type, platform, and scheduling

---

## Configuration

Key environment variables (`app/config.py`):

| Variable | Required | Purpose |
|---|---|---|
| `TMDB_API_KEY` | Yes | Movie/TV data from TMDb |
| `TAVILY_API_KEY` | Yes | Gossip headline scraping |
| `GEMINI_API_KEY` | Recommended | AI re-ranking via Gemini LLM |
| `TVDB_API_KEY` | Optional | Episode-level TV data |
| `CLERK_SECRET_KEY` | Optional | Clerk authentication |
| `CLERK_PUBLISHABLE_KEY` | Optional | Clerk frontend SDK |
| `SECRET_KEY` | Yes | Session encryption |

---

## Security

- External gossip links use `target="_blank" rel="noopener noreferrer"`
- API keys managed via Pydantic Settings (never hardcoded)
- Input validation via Pydantic models and FastAPI query/form types
- Session-based CSRF protection on all state-changing forms
- Rate limiting via `slowapi` on auth and API endpoints
- Jinja2 auto-escaping prevents XSS
