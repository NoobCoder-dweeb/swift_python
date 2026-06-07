from fastapi import APIRouter

from app.services.audit_service import AuditService

router = APIRouter()

audit_service = AuditService()


@router.get("/")
async def list_audits():
    """exposes persisted decisions for dashboards and compliance review."""
    return audit_service.list_audits()


@router.get("/{audit_id}")
async def get_audit(audit_id: str):
    """supports drill-down into one recorded workflow decision."""
    return audit_service.get_audit(audit_id)
