"""
Reminders routes
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.dependencies import DbDep, OptionalUserDep, RequireAuthDep
from app.models.reminder import ReminderType
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("", response_class=HTMLResponse)
def reminders_page(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
):
    from app.templates import templates

    if not user:
        return RedirectResponse(url="/login", status_code=303)

    tz = user.timezone or "UTC"
    svc = ReminderService(db)

    grouped, current_page, total_pages = svc.get_upcoming_grouped(user.id, page=page, tz_name=tz)

    now = datetime.now(UTC)
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
def create_reminder(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    date: Annotated[str, Form()],
    reminder_type: Annotated[str, Form()] = "premiere",
    time: Annotated[str, Form()] = "20:00",
    message: Annotated[str, Form()] = "",
    platform: Annotated[str | None, Form()] = None,
    quality: Annotated[str | None, Form()] = None,
    content_id: Annotated[int | None, Form()] = None,
):
    from app.templates import flash
    from app.utils.timezone import local_to_utc

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
def toggle_reminder(
    request: Request,
    reminder_id: int,
    user: OptionalUserDep,
    db: DbDep,
):
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    svc = ReminderService(db)
    svc.toggle_reminder(reminder_id, user.id)
    return RedirectResponse(url="/reminders", status_code=303)


@router.post("/{reminder_id}/delete")
def delete_reminder(
    request: Request,
    reminder_id: int,
    user: OptionalUserDep,
    db: DbDep,
):
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    svc = ReminderService(db)
    svc.delete_reminder(reminder_id, user.id)
    return RedirectResponse(url="/reminders", status_code=303)


class CalendarResponse(BaseModel):
    year: int
    month: int
    dates: dict[str, int]


@router.get("/api/calendar")
def calendar_data(
    user: RequireAuthDep,
    db: DbDep,
    year: Annotated[int, Query()],
    month: Annotated[int, Query()],
) -> CalendarResponse:
    tz = user.timezone or "UTC"
    svc = ReminderService(db)
    dots = svc.get_calendar_dots(user.id, year, month, tz_name=tz)
    return CalendarResponse(year=year, month=month, dates=dots)
