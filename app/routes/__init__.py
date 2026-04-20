"""
FastAPI Routers
"""
from app.routes import auth, dashboard, library, gossip, api, content, reminders, search_page, contact

__all__ = [
    "auth",
    "dashboard",
    "library",
    "gossip",
    "api",
    "content",
    "reminders",
    "search_page",
    "contact",
]
