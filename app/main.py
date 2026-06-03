from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.routing import NoMatchFound

from app.api.v1.routes import drafts, audits, health, emails
from data import RECORDS, USERS, get_audits, get_drafts

app = FastAPI(title="Project Swift Backend")

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(health.router)
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"])
app.include_router(audits.router, prefix="/api/audits", tags=["audits"])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"])


def _parse_sort_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def _sort_items(items, timestamp_key: str, order: str):
    reverse = order != "asc"
    return sorted(
        items,
        key=lambda item: _parse_sort_datetime(item.get(timestamp_key)),
        reverse=reverse,
    )


def _get_sort_order(request: Request) -> str:
    order = (request.query_params.get("order") or "desc").strip().lower()
    return "asc" if order == "asc" else "desc"


def _template_context(request: Request, **values):
    def url_for(name: str, **path_params):
        if name == "static" and "filename" in path_params:
            path_params["path"] = path_params.pop("filename")
        try:
            return request.url_for(name, **path_params)
        except NoMatchFound:
            url = request.url_for(name)
            return url.include_query_params(**path_params)

    return {"request": request, "url_for": url_for, **values}


@app.get("/")
async def home():
    return RedirectResponse(url="/dashboard", status_code=307)


@app.get("/dashboard", name="dashboard")
async def dashboard(request: Request):
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
    order = _get_sort_order(request)
    pending_drafts = _sort_items([d.to_dict() for d in get_drafts()], "created", order)
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context=_template_context(request, drafts=pending_drafts, sort_order=order),
    )


@app.get("/audit", name="audit_page")
async def audit_page(request: Request):
    order = _get_sort_order(request)
    sorted_audits = _sort_items(get_audits(), "timestamp", order)
    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context=_template_context(request, audits=sorted_audits, sort_order=order),
    )
