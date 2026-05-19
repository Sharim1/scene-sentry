"""
Public pages: privacy, terms, contact — and contact form API.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.routes.auth import limiter
from app.services.contact_service import deliver_contact_message
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pages"])


def _optional_user(request: Request) -> Optional[User]:
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    if not clerk_user_id and not session_user_id:
        return None
    db = next(get_db())
    try:
        uid = clerk_user_id or session_user_id
        return db.query(User).filter(User.id == uid).first()
    finally:
        db.close()


class ContactSubmissionIn(BaseModel):
    """Inbound JSON body for POST /contact."""

    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    subject: Optional[str] = Field(default=None, max_length=120)
    message: str = Field(min_length=10, max_length=2000)
    website: str = Field(default="", max_length=256)

    @field_validator("subject", mode="before")
    @classmethod
    def normalize_subject(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v


class ContactResponse(BaseModel):
    ok: bool
    delivered: Optional[bool] = None
    method: Optional[str] = None


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    user = _optional_user(request)
    return templates.TemplateResponse(
        "pages/privacy.html",
        {"request": request, "user": user},
    )


@router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    user = _optional_user(request)
    return templates.TemplateResponse(
        "pages/terms.html",
        {"request": request, "user": user},
    )


@router.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request):
    user = _optional_user(request)
    return templates.TemplateResponse(
        "pages/contact.html",
        {"request": request, "user": user},
    )


@router.post("/contact")
@limiter.limit(settings.rate_limit_auth)
def contact_submit(request: Request, body: ContactSubmissionIn) -> ContactResponse:
    """
    Accept contact form JSON. Honeypot field `website` must be empty.
    Bots that fill it get HTTP 200 with ok=true (silent success).
    """
    if body.website and body.website.strip():
        logger.debug("Contact form honeypot triggered — silent ok")
        return ContactResponse(ok=True)

    subj = body.subject.strip() if body.subject else None
    delivered, method = deliver_contact_message(
        name=body.name.strip(),
        email=str(body.email).strip(),
        subject=subj,
        message=body.message.strip(),
    )
    return ContactResponse(ok=True, delivered=delivered, method=method)
