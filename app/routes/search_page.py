"""
HTML catalog search page (server-rendered; complements /api/search for the modal).
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.repositories.content_repo import ContentRepository
from app.templates import templates

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def catalog_search_page(
    request: Request,
    q: str = Query("", alias="q"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    query = (q or "").strip()
    results = []
    if query:
        repo = ContentRepository(db)
        results = repo.search(query, limit=40)

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "user": user,
            "search_query": query,
            "results": results,
        },
    )
