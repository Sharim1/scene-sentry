"""
Jinja2 Templates Configuration

This module provides the Jinja2 templates instance to avoid circular imports.
"""

import json
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.config import settings

# Template paths
templates_path = Path(__file__).parent.parent / "templates"
static_path = Path(__file__).parent.parent / "static"

# Create Jinja2 templates instance
templates = Jinja2Templates(directory=templates_path)

# Flash message storage (request-scoped via context var)
_flash_messages: ContextVar[list[tuple[str, str]]] = ContextVar("flash_messages", default=[])


def from_json_filter(value):
    """Parse JSON string to Python object"""
    try:
        return json.loads(value) if value else []
    except (json.JSONDecodeError, TypeError):
        return []


def time_ago_filter(dt):
    """Convert datetime to human-readable 'time ago' string"""
    if not dt:
        return ""

    # Ensure timezone awareness
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    diff = now - dt
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    elif seconds < 604800:
        days = seconds // 86400
        return f"{days}d ago"
    elif seconds < 2592000:
        weeks = seconds // 604800
        return f"{weeks}w ago"
    else:
        return dt.strftime("%b %d")


def static_url(filename: str) -> str:
    """Generate static file URL for templates"""
    return f"/static/{filename}"


def flash(message: str, category: str = "info"):
    """Add a flash message to be displayed on next page load"""
    messages = _flash_messages.get()
    messages.append((category, message))
    _flash_messages.set(messages)


def get_flashed_messages(with_categories: bool = False):
    """Get and clear flash messages"""
    messages = _flash_messages.get()
    _flash_messages.set([])
    if with_categories:
        return messages
    return [msg for _, msg in messages]


def get_ai_status():
    """Get the current AI agent status based on configuration"""
    tavily_key = settings.tavily_api_key
    gemini_key = settings.gemini_api_key

    if not tavily_key:
        return {
            "status": "inactive",
            "message": "Tavily API key not configured",
            "details": "Add TAVILY_API_KEY to .env to enable gossip scraping",
            "color": "yellow",
        }

    if not gemini_key:
        return {
            "status": "limited",
            "message": "Gossip scraping enabled",
            "details": "Add GEMINI_API_KEY for AI-powered analysis",
            "color": "blue",
        }

    return {
        "status": "active",
        "message": "AI agents fully operational",
        "details": "Scraping variety.com, deadline.com...",
        "color": "green",
    }


def tojson_filter(value):
    """Serialize a value as JSON for embedding in <script> or data attributes."""
    return Markup(json.dumps(value))


def to_user_tz_filter(utc_dt, tz_name="UTC"):
    """Jinja2 filter: convert a UTC datetime to the given timezone."""
    from app.utils.timezone import utc_to_local

    return utc_to_local(utc_dt, tz_name)


# Register template filters and globals
templates.env.filters["from_json"] = from_json_filter
templates.env.filters["time_ago"] = time_ago_filter
templates.env.filters["to_user_tz"] = to_user_tz_filter
templates.env.filters["tojson"] = tojson_filter
templates.env.globals["static_url"] = static_url
templates.env.globals["get_flashed_messages"] = get_flashed_messages
templates.env.globals["get_ai_status"] = get_ai_status
templates.env.globals["flash"] = flash

# Clerk configuration for frontend
templates.env.globals["clerk_publishable_key"] = settings.clerk_publishable_key or ""
templates.env.globals["clerk_enabled"] = bool(settings.clerk_publishable_key and settings.clerk_issuer)
_clerk_fapi_url = ""
if settings.clerk_issuer:
    _clerk_fapi_url = settings.clerk_issuer.replace("https://", "").replace("http://", "")
templates.env.globals["clerk_fapi_url"] = _clerk_fapi_url
