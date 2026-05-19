"""
HTML catalog search page (server-rendered; complements /api/search for the modal).
"""
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import DbDep, OptionalUserDep
from app.repositories.content_repo import ContentRepository
from app.templates import templates

router = APIRouter(tags=["search"])


@router.get("/search", response_class=HTMLResponse)
def catalog_search_page(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    q: Annotated[str, Query()] = "",
):
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
