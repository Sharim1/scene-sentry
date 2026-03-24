"""
Notification REST + SSE endpoints
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/notifications")
async def list_notifications(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)

    svc = NotificationService(db)
    items = svc.get_for_user(user.id, limit=30)
    unread = svc.count_unread(user.id)
    return {
        "notifications": [svc.to_dict(n) for n in items],
        "unread_count": unread,
    }


@router.get("/notifications/unread-count")
async def unread_count(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)

    svc = NotificationService(db)
    return {"unread_count": svc.count_unread(user.id)}


@router.post("/notifications/{notification_id}/read")
async def mark_read(
    request: Request, notification_id: int, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)

    svc = NotificationService(db)
    n = svc.mark_read(notification_id, user.id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@router.post("/notifications/read-all")
async def mark_all_read(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401)

    svc = NotificationService(db)
    count = svc.mark_all_read(user.id)
    return {"success": True, "count": count}


@router.get("/notifications/stream")
async def notification_stream(request: Request, db: Session = Depends(get_db)):
    """SSE endpoint that pushes new notification events to the connected client.

    The stream polls the database every few seconds for new unread
    notifications created after the connection was established.  This is
    lightweight enough for a single-instance deployment; for multi-instance
    you would swap to Redis Pub/Sub.
    """
    user = get_current_user(request, db)
    if not user:
        async def empty():
            yield 'data: {"type":"auth_required"}\n\n'
        return StreamingResponse(empty(), media_type="text/event-stream")

    user_id = user.id

    async def event_generator():
        last_check = datetime.now(timezone.utc)
        yield f'data: {json.dumps({"type": "connected"})}\n\n'

        while True:
            try:
                await asyncio.sleep(5)

                from app.database import SessionLocal
                poll_db = SessionLocal()
                try:
                    svc = NotificationService(poll_db)
                    has_new = svc.has_unread_since(user_id, last_check)
                    if has_new:
                        unread = svc.count_unread(user_id)
                        recent = svc.get_for_user(user_id, unread_only=True, limit=5)
                        payload = {
                            "type": "new_notifications",
                            "unread_count": unread,
                            "items": [svc.to_dict(n) for n in recent],
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        last_check = datetime.now(timezone.utc)
                    else:
                        yield f'data: {json.dumps({"type": "keepalive"})}\n\n'
                finally:
                    poll_db.close()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("SSE poll error: %s", exc)
                yield f'data: {json.dumps({"type": "keepalive"})}\n\n'
                await asyncio.sleep(10)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
