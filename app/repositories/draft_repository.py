from __future__ import annotations

from typing import Any

from app.repositories.state_repository import get_state_repository


class DraftRepository:
    def __init__(self):
        self.repository = get_state_repository()

    def list(self) -> list[dict[str, Any]]:
        return self.repository.list_drafts()

    def get(self, draft_id: str) -> dict[str, Any] | None:
        return self.repository.get_draft(draft_id)

    def save(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self.repository.upsert_draft(draft)

    def delete(self, draft_id: str) -> None:
        self.repository.delete_draft(draft_id)
