import asyncio
import json
from collections import Counter
from datetime import datetime
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import NoMatchFound

import app.core.environment  # noqa: F401
from app.api.v1.routes import drafts, audits, health, emails
from app.core.config import get_app_settings
from app.services.auth_service import (
    authenticate,
    clear_session,
    current_account,
    list_accounts,
    open_session,
    role_can_view_all_pages,
)
from data import EVENTS_QUEUE, events_cond, get_audits, get_drafts

settings = get_app_settings()

app = FastAPI(title="Project Swift Backend")

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    same_site="lax",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates") if settings.ui_enabled else None

if settings.ui_enabled:
    app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(health.router)
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"])
app.include_router(audits.router, prefix="/api/audits", tags=["audits"])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"])


def _parse_sort_datetime(value: str | None) -> datetime:
    """keeps sorting stable even when legacy/demo rows have missing dates."""
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def _sort_items(items, timestamp_key: str, order: str):
    """centralizes page/API sort behavior so templates stay simple."""
    reverse = order != "asc"
    return sorted(
        items,
        key=lambda item: _parse_sort_datetime(item.get(timestamp_key)),
        reverse=reverse,
    )


def _get_sort_order(request: Request) -> str:
    """normalizes user input so unsupported values cannot flip sort logic."""
    order = (request.query_params.get("order") or "desc").strip().lower()
    return "asc" if order == "asc" else "desc"


def _template_context(request: Request, **values):
    """preserves Flask-style template helpers while using FastAPI routing."""
    def url_for(name: str, **path_params):
        """lets existing templates call url_for without framework-specific edits."""
        if name == "static" and "filename" in path_params:
            path_params["path"] = path_params.pop("filename")
        try:
            return request.url_for(name, **path_params)
        except NoMatchFound:
            url = request.url_for(name)
            return url.include_query_params(**path_params)

    account = current_account(request)
    return {
        "request": request,
        "url_for": url_for,
        "current_user": account.public_dict() if account else None,
        "can_view_all_pages": account.can_view_all_pages if account else False,
        **values,
    }


def _safe_next_path(value: str | None) -> str:
    """allows only app-local redirect targets after login."""
    next_path = (value or "/dashboard").strip()
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/dashboard"
    return next_path


def _login_redirect(request: Request) -> RedirectResponse | None:
    """redirects anonymous UI users to the sales officer login page."""
    if current_account(request):
        return None

    next_path = _safe_next_path(str(request.url.path))
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(next_path, safe='')}",
        status_code=303,
    )


def _path_allowed_for_role(path: str, role: str) -> bool:
    """keeps regular sales users on their two allowed UI pages."""
    if role_can_view_all_pages(role):
        return True
    return (path or "").split("?", 1)[0] in {"/", "/dashboard", "/pending"}


def _require_all_pages_access(request: Request) -> None:
    """blocks manager/admin-only pages from regular sales accounts."""
    account = current_account(request)
    if account and account.can_view_all_pages:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This page is available to admins and sales managers only.",
    )


def _labelize(value: str | None) -> str:
    """formats compact stored statuses/actions for dashboards."""
    return (value or "unknown").replace("_", " ").replace("-", " ").title()


def _badge_class(value: str | None) -> str:
    """maps workflow states to existing badge styles."""
    normalized = (value or "").strip().lower()
    if normalized in {"approved", "accepted", "sent"}:
        return "badge-success"
    if normalized in {"rejected", "failed"}:
        return "badge-danger"
    if normalized in {"pending", "edited"}:
        return "badge-warning"
    return "badge-primary"


def _dashboard_context() -> dict:
    """builds a sales-focused dashboard from live review/audit data."""
    pending_drafts = _sort_items(
        [d.to_dict() for d in get_drafts()], "created", "desc"
    )
    audits = _sort_items(get_audits(), "timestamp", "desc")
    action_counts = Counter(
        (audit.get("action") or "unknown").lower() for audit in audits
    )
    approved_count = action_counts["approved"] + action_counts["accepted"]
    rejected_count = action_counts["rejected"]
    edited_count = action_counts["edited"]
    total_items = len(pending_drafts) + approved_count + rejected_count + edited_count

    status_breakdown = [
        ("Pending", len(pending_drafts), "var(--warning)"),
        ("Approved", approved_count, "var(--success)"),
        ("Rejected", rejected_count, "var(--danger)"),
        ("Edited", edited_count, "var(--primary)"),
    ]

    return {
        "stats": [
            {
                "label": "Pending Reviews",
                "value": len(pending_drafts),
                "detail": "Awaiting sales approval",
                "icon": "ph-clock",
                "tone": "warning",
            },
            {
                "label": "Approved",
                "value": approved_count,
                "detail": "Responses cleared",
                "icon": "ph-check-circle",
                "tone": "success",
            },
            {
                "label": "Rejected",
                "value": rejected_count,
                "detail": "Returned for regeneration",
                "icon": "ph-x-circle",
                "tone": "danger",
            },
            {
                "label": "Edited",
                "value": edited_count,
                "detail": "Manually revised",
                "icon": "ph-pencil-simple",
                "tone": "primary",
            },
        ],
        "pending_drafts": pending_drafts[:6],
        "recent_audits": [
            {
                **audit,
                "action_label": _labelize(audit.get("action")),
                "badge_class": _badge_class(audit.get("action")),
            }
            for audit in audits[:6]
        ],
        "status_breakdown": [
            {
                "label": label,
                "count": count,
                "color": color,
                "percentage": (
                    round((count / total_items) * 100) if total_items else 0
                ),
            }
            for label, count, color in status_breakdown
        ],
        "total_items": total_items,
    }


@app.get("/")
async def home():
    """routes humans to UI when bundled UI is enabled, otherwise describes APIs."""
    if not settings.ui_enabled:
        return {
            "service": "project-swift",
            "mode": "api-only",
            "settings": settings.public_dict(),
            "endpoints": {
                "health": "/health",
                "drafts": "/api/drafts/",
                "emails": "/api/emails/ingest",
                "audits": "/api/audits",
                "events": "/stream",
            },
        }
    return RedirectResponse(url="/dashboard", status_code=307)


if settings.ui_enabled:

    @app.get("/login", name="login_page")
    async def login_page(request: Request, next: str = "/dashboard"):
        """renders the sales officer login page."""
        if current_account(request):
            return RedirectResponse(url=_safe_next_path(next), status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=_template_context(
                request,
                accounts=list_accounts(),
                next_path=_safe_next_path(next),
                error="",
            ),
        )

    @app.post("/login", name="login")
    async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        next: str = Form("/dashboard"),
    ):
        """authenticates a sales officer and opens a signed session."""
        next_path = _safe_next_path(next)
        account = authenticate(username, password)
        if not account:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=_template_context(
                    request,
                    accounts=list_accounts(),
                    next_path=next_path,
                    error="Invalid username or password.",
                    attempted_username=(username or "").strip(),
                ),
                status_code=401,
            )

        open_session(request, account)
        if not _path_allowed_for_role(next_path, account.role):
            next_path = "/dashboard"
        return RedirectResponse(url=next_path, status_code=303)

    @app.post("/logout", name="logout")
    async def logout(request: Request):
        """signs out the current sales officer."""
        clear_session(request)
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/dashboard", name="dashboard")
    async def dashboard(request: Request):
        """renders the top-level work queue summary for human reviewers."""
        redirect = _login_redirect(request)
        if redirect:
            return redirect
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=_template_context(request, **_dashboard_context()),
        )

    @app.get("/pending", name="pending_page")
    async def pending_page(request: Request):
        """exposes database-backed drafts that still need sales approval."""
        redirect = _login_redirect(request)
        if redirect:
            return redirect
        order = _get_sort_order(request)
        pending_drafts = _sort_items(
            [d.to_dict() for d in get_drafts()], "created", order
        )
        return templates.TemplateResponse(
            request=request,
            name="pending.html",
            context=_template_context(request, drafts=pending_drafts, sort_order=order),
        )

    @app.get("/audit", name="audit_page")
    async def audit_page(request: Request):
        """gives reviewers a human-readable history of decisions."""
        redirect = _login_redirect(request)
        if redirect:
            return redirect
        _require_all_pages_access(request)
        order = _get_sort_order(request)
        sorted_audits = _sort_items(get_audits(), "timestamp", order)
        return templates.TemplateResponse(
            request=request,
            name="audit.html",
            context=_template_context(request, audits=sorted_audits, sort_order=order),
        )


def _wait_for_sse_events(timeout: float = 1.0) -> list[dict]:
    """blocks briefly to avoid tight polling while keeping SSE responsive."""
    with events_cond:
        events_cond.wait(timeout=timeout)
        events = list(EVENTS_QUEUE)
        EVENTS_QUEUE.clear()
        return events


@app.get("/stream")
async def stream(request: Request):
    """pushes draft/audit changes to the browser without page refreshes."""
    async def event_stream():
        """isolates the generator lifecycle so disconnects stop cleanly."""
        try:
            while not await request.is_disconnected():
                events = await asyncio.to_thread(_wait_for_sse_events)
                if not events:
                    yield ": keep-alive\n\n"
                    continue

                for event in events:
                    payload = event.get("payload", event)
                    event_type = event.get("type", "message")
                    yield f"event: {event_type}\n"
                    yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
