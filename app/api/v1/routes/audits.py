from fastapi import APIRouter

from app.services.audit_service import AuditService

router = APIRouter()

audit_service = AuditService()


@router.get("/")
async def list_audits():
    return audit_service.list_audits()


@router.get("/{audit_id}")
async def get_audit(audit_id: str):
    return audit_service.get_audit(audit_id)
