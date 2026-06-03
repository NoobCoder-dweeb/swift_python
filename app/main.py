from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from app.api.v1.routes import drafts, audits, health, emails

app = FastAPI(title="Project Swift Backend")

templates = Jinja2Templates(directory="templates")

app.include_router(health.router)
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"])
app.include_router(audits.router, prefix="/api/audits", tags=["audits"])
app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
