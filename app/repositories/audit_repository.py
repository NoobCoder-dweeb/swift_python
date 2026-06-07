from __future__ import annotations

from typing import Any

from app.repositories.state_repository import get_state_repository


class AuditRepository:
    def __init__(self):
        self.repository = get_state_repository()

    def list(self) -> list[dict[str, Any]]:
        return self.repository.list_audits()

    def get(self, audit_id: str) -> dict[str, Any] | None:
        return self.repository.get_audit(audit_id)

    def insert(self, audit: dict[str, Any]) -> dict[str, Any]:
        return self.repository.insert_audit(audit)
