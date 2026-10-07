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
    "contact",
]
