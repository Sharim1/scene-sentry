"""
FastAPI Routers
"""
from app.routes import auth, dashboard, library, gossip, api, content, reminders

__all__ = ["auth", "dashboard", "library", "gossip", "api", "content", "reminders"]
