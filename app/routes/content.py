"""
Content routes: the unified search/browse page and content detail pages.
"""

import json as _json
import logging
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import DbDep, OptionalUserDep, login_redirect
from app.repositories.content_repo import ContentRepository
from app.repositories.episode_repo import EpisodeRepository
from app.repositories.library_repo import LibraryRepository
from app.services.library_service import LibraryService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["content"])

PER_PAGE = 40


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    q: Annotated[str | None, Query()] = None,
    type: Annotated[str, Query()] = "all",
    genre: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "relevance",
    page: Annotated[int, Query(ge=1)] = 1,
):
    """The full catalog, reached only by searching, a genre shortcut, or a "See all" link.

    There is no standalone browse page for movies or TV shows — this page covers both.
    """
    from app.templates import templates

    if not user:
        return login_redirect(request)

    repo = ContentRepository(db)
    offset = (page - 1) * PER_PAGE
    results, total = repo.browse(query_str=q, content_type=type, genre=genre, sort=sort, limit=PER_PAGE, offset=offset)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    lib_repo = LibraryRepository(db)
    library_items_map = {item.content_id: item for item in lib_repo.get_by_user(user.id)}

    return templates.TemplateResponse(
        "search_results.html",
        {
            "request": request,
            "user": user,
            "results": results,
            "search_query": q or "",
            "current_type": type,
            "current_genre": genre or "",
            "current_sort": sort,
            "library_items_map": library_items_map,
            "page": page,
            "total_pages": total_pages,
            "total_count": total,
        },
    )


@router.post("/add-to-library")
def add_to_library(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    content_id: Annotated[int, Form()],
    status: Annotated[str, Form()] = "planned",
):
    if not user:
        return login_redirect(request)

    svc = LibraryService(db)
    existing = LibraryRepository(db).get_by_user_and_content(user.id, content_id)

    if existing:
        svc.update_status(user.id, existing.id, status)
    else:
        svc.add(user.id, content_id, status)

    referer = request.headers.get("referer", "/dashboard")
    if not referer.startswith("/"):
        from urllib.parse import urlparse

        parsed = urlparse(referer)
        referer = parsed.path or "/dashboard"
    return RedirectResponse(url=referer, status_code=303)


@router.get("/{content_id}", response_class=HTMLResponse)
def content_detail(
    request: Request,
    content_id: int,
    user: OptionalUserDep,
    db: DbDep,
):
    from app.templates import templates

    if not user:
        return login_redirect(request)

    content = ContentRepository(db).get_by_id(content_id)
    if not content:
        return RedirectResponse(url="/dashboard", status_code=303)

    library_item = LibraryRepository(db).get_by_user_and_content(user.id, content_id)

    episodes = []
    seasons_map: dict = {}
    if content.content_type == "tv_show":
        ep_repo = EpisodeRepository(db)
        episodes = ep_repo.get_by_content(content_id)
        for ep in episodes:
            seasons_map.setdefault(ep.season_number, []).append(ep)

    genres = []
    if content.genres:
        try:
            genres = _json.loads(content.genres)
        except (ValueError, TypeError):
            genres = []

    return templates.TemplateResponse(
        "content_detail.html",
        {
            "request": request,
            "user": user,
            "content": content,
            "library_item": library_item,
            "episodes": episodes,
            "seasons_map": seasons_map,
            "genres": genres,
        },
    )
