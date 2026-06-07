from uuid import uuid4
from datetime import datetime

from app.repositories.state_repository import get_state_repository


class AuditService:
    def __init__(self):
        self.repository = get_state_repository()

    def create_audit(
        self,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        details: dict | None = None,
    ):
        audit_id = f"AUD-{uuid4().hex[:8].upper()}"

        audit = {
            "audit_id": audit_id,
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
            "created_at": datetime.now().isoformat(),
        }

        return self.repository.insert_audit(audit)

    def list_audits(self):
        return self.repository.list_audits()

    def get_audit(self, audit_id: str):
        return self.repository.get_audit(audit_id)
