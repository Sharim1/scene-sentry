"""
Content routes for Movies and TV Shows
"""
import logging
from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.database import get_db
from app.models import User, Content, LibraryItem, WatchStatus
from app.routes.auth import get_current_user
from app.repositories.content_repo import ContentRepository
from app.repositories.library_repo import LibraryRepository
from app.services.ranking_service import RankingService

logger = logging.getLogger(__name__)
router = APIRouter()

PER_PAGE = 40


@router.get("/movies", response_class=HTMLResponse)
async def movies_page(
    request: Request,
    filter: str = Query("all"),
    q: str = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    from app.templates import templates

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    repo = ContentRepository(db)
    total = repo.count("movie")
    offset = (page - 1) * PER_PAGE

    if q:
        movies = repo.search(q, content_type="movie", limit=PER_PAGE)
        total = len(movies)
    else:
        ranking_svc = RankingService(db)
        ranked = ranking_svc.get_personalized_content(user.id, content_type="movie", limit=PER_PAGE)
        if ranked and ranked[0][1] is not None:
            movies = [r[0] for r in ranked]
        else:
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
async def tv_shows_page(
    request: Request,
    filter: str = Query("all"),
    q: str = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    from app.templates import templates

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    repo = ContentRepository(db)
    total = repo.count("tv_show")
    offset = (page - 1) * PER_PAGE

    if q:
        tv_shows = repo.search(q, content_type="tv_show", limit=PER_PAGE)
        total = len(tv_shows)
    else:
        ranking_svc = RankingService(db)
        ranked = ranking_svc.get_personalized_content(user.id, content_type="tv_show", limit=PER_PAGE)
        if ranked and ranked[0][1] is not None:
            tv_shows = [r[0] for r in ranked]
        else:
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
async def add_to_library(
    request: Request,
    content_id: int = Form(...),
    status: str = Form("planned"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    status_map = {
        "watching": WatchStatus.WATCHING,
        "planned": WatchStatus.PLANNED,
        "completed": WatchStatus.COMPLETED,
        "dropped": WatchStatus.DROPPED,
        "maybe": WatchStatus.MAYBE,
    }
    watch_status = status_map.get(status, WatchStatus.PLANNED)

    lib_repo = LibraryRepository(db)
    existing = lib_repo.get_by_user_and_content(user.id, content_id)

    if existing:
        existing.status = watch_status
        existing.updated_at = datetime.now(timezone.utc)
    else:
        content = ContentRepository(db).get_by_id(content_id)
        if content:
            lib_repo.create(user_id=user.id, content_id=content_id, status=watch_status)

    db.commit()

    RankingService(db).invalidate_ranks(user.id)

    referer = request.headers.get("referer", "/movies")
    return RedirectResponse(url=referer, status_code=303)


@router.get("/{content_id}", response_class=HTMLResponse)
async def content_detail(
    request: Request,
    content_id: int,
    db: Session = Depends(get_db),
):
    from app.templates import templates
    from app.repositories.episode_repo import EpisodeRepository
    import json as _json

    user = get_current_user(request, db)
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
