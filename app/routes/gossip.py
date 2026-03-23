"""
Gossip routes for entertainment news
"""
import logging
from fastapi import APIRouter, Request, Depends, Query, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.gossip import GossipTag
from app.routes.auth import get_current_user
from app.services.gossip_service import GossipService
from app.repositories.library_repo import LibraryRepository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def gossip_feed(
    request: Request,
    tag: str = Query(None),
    db: Session = Depends(get_db),
):
    from app.templates import templates

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    svc = GossipService(db)
    gossip_items = svc.get_feed(tag=tag, limit=50)
    tag_counts = svc.get_tag_counts()

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
async def gossip_detail(
    request: Request,
    gossip_id: int,
    db: Session = Depends(get_db),
):
    """Redirect to the original article source."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    svc = GossipService(db)
    gossip = svc.get_by_id(gossip_id)
    if not gossip or not gossip.source_url:
        return RedirectResponse(url="/gossip", status_code=303)

    gossip.view_count += 1
    db.commit()

    return RedirectResponse(url=gossip.source_url, status_code=302)


@router.post("/refresh")
async def refresh_gossip(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from app.services.task_manager import get_task_manager, TaskType

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    task_manager = get_task_manager()
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == TaskType.GOSSIP_SCRAPE:
            return RedirectResponse(url="/gossip", status_code=303)

    lib_repo = LibraryRepository(db)
    tracked_titles = lib_repo.get_tracked_titles(user.id)

    task = await task_manager.create_task(
        task_type=TaskType.GOSSIP_SCRAPE,
        user_id=user.id,
        name="Scanning for Gossip",
    )

    async def run_gossip_scrape(task, tm):
        from app.services.gossip_service import GossipService as GS

        await tm.update_task(task.id, progress=10, message=f"Scanning news for {len(tracked_titles)} tracked titles...")
        try:
            db_gen = get_db()
            db_session = next(db_gen)
            try:
                svc = GS(db_session)
                results = await svc.scrape_latest(tracked_titles)
                await tm.update_task(task.id, progress=90, message=f"Found {len(results)} gossip items")
                return {"scraped": len(results)}
            finally:
                db_session.close()
        except Exception as e:
            logger.error(f"Gossip scrape error: {e}")
            raise

    background_tasks.add_task(task_manager.run_task, task.id, run_gossip_scrape)
    return RedirectResponse(url="/gossip", status_code=303)
