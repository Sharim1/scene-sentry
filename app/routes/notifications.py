"""
Notification REST + SSE endpoints
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import DbDep, OptionalUserDep, RequireAuthDep
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["notifications"])


class NotificationItem(BaseModel):
    id: int
    title: str
    body: str | None
    link: str | None
    is_read: bool
    created_at: str | None


class NotificationListResponse(BaseModel):
    notifications: list[NotificationItem]
    unread_count: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class SuccessResponse(BaseModel):
    success: bool


class MarkAllReadResponse(BaseModel):
    success: bool
    count: int


@router.get("/notifications")
def list_notifications(user: RequireAuthDep, db: DbDep) -> NotificationListResponse:
    svc = NotificationService(db)
    items = svc.get_for_user(user.id, limit=30)
    unread = svc.count_unread(user.id)
    return NotificationListResponse(
        notifications=[NotificationItem(**svc.to_dict(n)) for n in items],
        unread_count=unread,
    )


@router.get("/notifications/unread-count")
def unread_count(user: RequireAuthDep, db: DbDep) -> UnreadCountResponse:
    svc = NotificationService(db)
    return UnreadCountResponse(unread_count=svc.count_unread(user.id))


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: RequireAuthDep,
    db: DbDep,
) -> SuccessResponse:
    svc = NotificationService(db)
    n = svc.mark_read(notification_id, user.id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    return SuccessResponse(success=True)


@router.post("/notifications/read-all")
def mark_all_read(user: RequireAuthDep, db: DbDep) -> MarkAllReadResponse:
    svc = NotificationService(db)
    count = svc.mark_all_read(user.id)
    return MarkAllReadResponse(success=True, count=count)


@router.get("/notifications/stream")
async def notification_stream(request: Request, user: OptionalUserDep):
    """SSE endpoint that pushes new notification events to the connected client.

    The stream polls the database every few seconds for new unread
    notifications created after the connection was established.
    """
    if not user:

        async def empty():
            yield 'data: {"type":"auth_required"}\n\n'

        return StreamingResponse(empty(), media_type="text/event-stream")

    user_id = user.id

    async def event_generator():
        last_check = datetime.now(UTC)
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"

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
                        last_check = datetime.now(UTC)
                    else:
                        yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
                finally:
                    poll_db.close()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("SSE poll error: %s", exc)
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
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
