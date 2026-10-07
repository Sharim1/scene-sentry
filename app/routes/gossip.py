"""
Gossip routes for entertainment news
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import DbDep, OptionalUserDep, login_redirect
from app.models.gossip import GossipTag
from app.repositories.gossip_repo import GossipRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gossip", tags=["gossip"])


@router.get("", response_class=HTMLResponse)
def gossip_feed(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    tag: Annotated[str | None, Query()] = None,
):
    from app.templates import templates

    if not user:
        return login_redirect(request)

    repo = GossipRepository(db)
    gossip_items = repo.get_feed(tag=tag, limit=50)
    tag_counts = repo.get_tag_counts()

    return templates.TemplateResponse(
        "gossip/feed.html",
        {
            "request": request,
            "user": user,
            "gossip_items": gossip_items,
            "current_tag": tag,
            "tag_counts": tag_counts,
            "all_tags": [t.value for t in GossipTag],
        },
    )


@router.get("/{gossip_id}")
def gossip_detail(
    request: Request,
    gossip_id: int,
    user: OptionalUserDep,
    db: DbDep,
):
    """Redirect to the original article source."""
    if not user:
        return login_redirect(request)

    repo = GossipRepository(db)
    gossip = repo.get_by_id(gossip_id)
    if not gossip or not gossip.source_url:
        return RedirectResponse(url="/gossip", status_code=303)

    gossip.view_count += 1
    db.commit()

    from urllib.parse import urlparse

    parsed = urlparse(gossip.source_url)
    if parsed.scheme not in ("http", "https"):
        return RedirectResponse(url="/gossip", status_code=303)
    return RedirectResponse(url=gossip.source_url, status_code=302)
