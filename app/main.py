import asyncio
import json
from datetime import datetime
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
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
)
from data import EVENTS_QUEUE, RECORDS, USERS, events_cond, get_audits, get_drafts

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
        stats = {
            "total_records": len(RECORDS),
            "active_users": len(USERS),
            "pending_reviews": len(get_drafts()),
            "resolved_issues": 847,
        }
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=_template_context(request, stats=stats, records=RECORDS[:5]),
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
