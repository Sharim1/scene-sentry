"""
Content routes for Movies and TV Shows
"""

import json as _json
import logging
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import DbDep, OptionalUserDep
from app.repositories.content_repo import ContentRepository
from app.repositories.episode_repo import EpisodeRepository
from app.repositories.library_repo import LibraryRepository
from app.repositories.ranking_repo import RankingRepository
from app.services.library_service import LibraryService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["content"])

PER_PAGE = 40


@router.get("/movies", response_class=HTMLResponse)
def movies_page(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    filter: Annotated[str, Query()] = "all",
    q: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
):
    from app.templates import templates

    if not user:
        return RedirectResponse(url="/login", status_code=303)

    repo = ContentRepository(db)
    total = repo.count("movie")

    if q:
        movies = repo.search(q, content_type="movie", limit=PER_PAGE)
        total = len(movies)
    else:
        ranking_repo = RankingRepository(db)
        ranked = ranking_repo.get_ranked_content(user.id, content_type="movie", limit=PER_PAGE)
        if ranked and ranked[0][1] is not None:
            movies = [r[0] for r in ranked]
        else:
            offset = (page - 1) * PER_PAGE
            movies = repo.get_movies(filter_by=filter, search=q, limit=PER_PAGE, offset=offset)

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    lib_repo = LibraryRepository(db)
    library_items = lib_repo.get_by_user(user.id)
    library_status = {item.content_id: item.status.value for item in library_items}

    return templates.TemplateResponse(
        "movies.html",
        {
            "request": request,
            "user": user,
            "movies": movies,
            "current_filter": filter,
            "search_query": q,
            "library_status": library_status,
            "page": page,
            "total_pages": total_pages,
            "total_count": total,
        },
    )


@router.get("/tv-shows", response_class=HTMLResponse)
def tv_shows_page(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    filter: Annotated[str, Query()] = "all",
    q: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
):
    from app.templates import templates

    if not user:
        return RedirectResponse(url="/login", status_code=303)

    repo = ContentRepository(db)
    total = repo.count("tv_show")

    if q:
        tv_shows = repo.search(q, content_type="tv_show", limit=PER_PAGE)
        total = len(tv_shows)
    else:
        ranking_repo = RankingRepository(db)
        ranked = ranking_repo.get_ranked_content(user.id, content_type="tv_show", limit=PER_PAGE)
        if ranked and ranked[0][1] is not None:
            tv_shows = [r[0] for r in ranked]
        else:
            offset = (page - 1) * PER_PAGE
            tv_shows = repo.get_tv_shows(filter_by=filter, search=q, limit=PER_PAGE, offset=offset)

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    lib_repo = LibraryRepository(db)
    library_items = lib_repo.get_by_user(user.id)
    library_status = {item.content_id: item.status.value for item in library_items}

    return templates.TemplateResponse(
        "tv_shows.html",
        {
            "request": request,
            "user": user,
            "tv_shows": tv_shows,
            "current_filter": filter,
            "search_query": q,
            "library_status": library_status,
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
        return RedirectResponse(url="/login", status_code=303)

    svc = LibraryService(db)
    existing = LibraryRepository(db).get_by_user_and_content(user.id, content_id)

    if existing:
        svc.update_status(user.id, existing.id, status)
    else:
        svc.add(user.id, content_id, status)

    referer = request.headers.get("referer", "/movies")
    if not referer.startswith("/"):
        from urllib.parse import urlparse

        parsed = urlparse(referer)
        referer = parsed.path or "/movies"
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
        return RedirectResponse(url="/login", status_code=303)

    content = ContentRepository(db).get_by_id(content_id)
    if not content:
        return RedirectResponse(url="/movies", status_code=303)

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
