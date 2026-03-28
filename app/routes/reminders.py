"""
Reminders routes
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.reminder_service import ReminderService
from app.models.reminder import ReminderType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def reminders_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    from app.templates import templates

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    tz = user.timezone or "UTC"
    svc = ReminderService(db)

    grouped, current_page, total_pages = svc.get_upcoming_grouped(
        user.id, page=page, tz_name=tz,
    )

    now = datetime.now(timezone.utc)
    calendar_dots = svc.get_calendar_dots(user.id, now.year, now.month, tz_name=tz)

    return templates.TemplateResponse(
        "reminders.html",
        {
            "request": request,
            "user": user,
            "grouped_reminders": grouped,
            "calendar_dots": calendar_dots,
            "calendar_year": now.year,
            "calendar_month": now.month,
            "page": current_page,
            "total_pages": total_pages,
        },
    )


@router.post("/create")
async def create_reminder(
    request: Request,
    content_id: int = Form(None),
    reminder_type: str = Form("premiere"),
    date: str = Form(...),
    time: str = Form("20:00"),
    message: str = Form(""),
    platform: str = Form(None),
    quality: str = Form(None),
    db: Session = Depends(get_db),
):
    from app.utils.timezone import local_to_utc
    from app.templates import flash

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    type_map = {t.value: t for t in ReminderType}
    rtype = type_map.get(reminder_type, ReminderType.PREMIERE)

    tz = user.timezone or "UTC"

    try:
        naive = datetime.strptime(f"{date}T{time}", "%Y-%m-%dT%H:%M")
        sched = local_to_utc(naive, tz)
    except (ValueError, TypeError):
        flash("Invalid date or time format. Please try again.", "error")
        return RedirectResponse(url="/reminders", status_code=303)

    svc = ReminderService(db)
    svc.create_reminder(
        user_id=user.id,
        content_id=content_id,
        reminder_type=rtype,
        scheduled_time=sched,
        message=message,
        platform=platform,
        quality=quality,
    )

    return RedirectResponse(url="/reminders", status_code=303)


@router.post("/{reminder_id}/toggle")
async def toggle_reminder(
    request: Request,
    reminder_id: int,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    svc = ReminderService(db)
    svc.toggle_reminder(reminder_id, user.id)
    return RedirectResponse(url="/reminders", status_code=303)


@router.post("/{reminder_id}/delete")
async def delete_reminder(
    request: Request,
    reminder_id: int,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    svc = ReminderService(db)
    svc.delete_reminder(reminder_id, user.id)
    return RedirectResponse(url="/reminders", status_code=303)


@router.get("/api/calendar")
async def calendar_data(
    request: Request,
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tz = user.timezone or "UTC"
    svc = ReminderService(db)
    dots = svc.get_calendar_dots(user.id, year, month, tz_name=tz)
    return {"year": year, "month": month, "dates": dots}
