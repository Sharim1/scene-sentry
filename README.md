# MovieMind

AI-powered entertainment discovery and gossip platform. Get personalized recommendations, track your watchlist, and stay updated with the latest entertainment news.

## Features

- **AI-Powered Discovery**: LangGraph-orchestrated agents that search and analyze entertainment content
- **Entertainment Gossip**: Real-time scraping of news from Variety, Deadline, Hollywood Reporter, and more
- **Smart Recommendations**: Personalized suggestions based on your taste and viewing history
- **Library Management**: Track what you're watching, planning to watch, or have completed
- **Book-to-Screen Tracking**: Follow your favorite book adaptations from announcement to premiere

## Tech Stack

- **Backend**: FastAPI + Python 3.11+
- **Database**: SQLAlchemy ORM (SQLite for dev, PostgreSQL for production)
- **AI**: LangChain + LangGraph + Google Gemini
- **Search**: Tavily API for web scraping
- **Frontend**: Jinja2 templates + Tailwind CSS + Alpine.js
- **Auth**: Session-based (Clerk integration ready)

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Node.js (optional, for Tailwind CSS compilation)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd MovieMind
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

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys
```

5. Run the application:
```bash
python run.py
# Or:
uvicorn app.main:app --reload --port 5000
```

6. Open http://localhost:5000 in your browser

### Required API Keys

- **GEMINI_API_KEY**: Get from [Google AI Studio](https://aistudio.google.com/)
- **TAVILY_API_KEY**: Get from [Tavily](https://tavily.com/)
- **TMDB_API_KEY**: Get from [TMDb](https://www.themoviedb.org/settings/api)

## Project Structure

```
MovieMind/
├── app/                    # FastAPI application
│   ├── agents/            # AI agents (discovery, gossip)
│   ├── models/            # SQLAlchemy models
│   ├── routes/            # API routes
│   ├── services/          # Business logic
│   ├── tasks/             # Background tasks
│   ├── config.py          # Settings
│   ├── database.py        # Database setup
│   └── main.py            # FastAPI app
├── templates/             # Jinja2 templates
│   ├── partials/          # Reusable components
│   ├── auth/              # Auth pages
│   ├── gossip/            # Gossip pages
│   └── errors/            # Error pages
├── static/                # Static files
│   ├── css/               # Stylesheets
│   ├── js/                # JavaScript
│   └── images/            # Images
├── run.py                 # Entry point
└── pyproject.toml         # Dependencies
```

## Development

### Running Tests
```bash
pytest
```

### Database Migrations
The app uses SQLAlchemy with automatic table creation. For schema changes, you may need to recreate the database during development:
```bash
rm moviemind.db
python run.py
```

### Tailwind CSS
Tailwind is loaded via CDN in development. For production, you can compile:
```bash
npx tailwindcss -i ./static/css/input.css -o ./static/css/app.css --minify
```

## License

MIT License
