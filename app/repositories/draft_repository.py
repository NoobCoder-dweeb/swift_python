from __future__ import annotations

from typing import Any

from app.repositories.state_repository import get_state_repository


class DraftRepository:
    """keeps draft repository imports stable while storage lives in StateRepository."""

    def __init__(self):
        """delegates to one configured backend for runtime consistency."""
        self.repository = get_state_repository()

    def list(self) -> list[dict[str, Any]]:
        """exposes stored drafts through the legacy repository API."""
        return self.repository.list_drafts()

    def get(self, draft_id: str) -> dict[str, Any] | None:
        """preserves direct draft lookup for callers using this wrapper."""
        return self.repository.get_draft(draft_id)

    def save(self, draft: dict[str, Any]) -> dict[str, Any]:
        """keeps create/update behavior behind one repository method."""
        return self.repository.upsert_draft(draft)

    def delete(self, draft_id: str) -> None:
        """removes reviewed drafts through the shared storage backend."""
        self.repository.delete_draft(draft_id)
