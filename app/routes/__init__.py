"""
FastAPI Routers
"""
from app.routes import (
    api,
    auth,
    contact,
    content,
    dashboard,
    gossip,
    library,
    notifications,
    reminders,
    search_page,
)

__all__ = [
    "auth",
    "dashboard",
    "library",
    "gossip",
    "api",
    "content",
    "reminders",
    "notifications",
    "search_page",
    "contact",
]
