from uuid import uuid4
from datetime import datetime


class AuditService:
    def __init__(self):
        self.audits = {}

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

        self.audits[audit_id] = audit
        return audit

    def list_audits(self):
        return list(self.audits.values())

    def get_audit(self, audit_id: str):
        return self.audits.get(audit_id)
