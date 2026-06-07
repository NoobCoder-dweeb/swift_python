from __future__ import annotations

from typing import Any


class AuditLogger:
    def __init__(self, postgres_client):
        self.postgres_client = postgres_client

    def save(self, log_data: dict[str, Any]) -> None:
        self.postgres_client.insert("audit_logs", log_data)
