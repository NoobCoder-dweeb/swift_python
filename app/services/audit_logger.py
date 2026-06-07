from __future__ import annotations

from typing import Any


class AuditLogger:
    """gives tests and future agents a minimal PostgreSQL audit sink."""

    def __init__(self, postgres_client):
        """accepts a client dependency so persistence can be mocked in tests."""
        self.postgres_client = postgres_client

    def save(self, log_data: dict[str, Any]) -> None:
        """writes decisions to a single audit log table for traceability."""
        self.postgres_client.insert("audit_logs", log_data)
