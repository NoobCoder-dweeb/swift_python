from __future__ import annotations

from typing import Any

from app.repositories.state_repository import get_state_repository


class AuditRepository:
    """keeps older repository imports working after the shared state refactor."""

    def __init__(self):
        """delegates to the configured state repository instead of duplicating logic."""
        self.repository = get_state_repository()

    def list(self) -> list[dict[str, Any]]:
        """exposes audit rows through the legacy repository API."""
        return self.repository.list_audits()

    def get(self, audit_id: str) -> dict[str, Any] | None:
        """preserves direct audit lookup for callers using this wrapper."""
        return self.repository.get_audit(audit_id)

    def insert(self, audit: dict[str, Any]) -> dict[str, Any]:
        """centralizes audit writes in the shared persistence layer."""
        return self.repository.insert_audit(audit)
