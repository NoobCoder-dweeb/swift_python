from __future__ import annotations

from typing import Any, Protocol


AUDIT_LOG_TABLE = "audit_logs"


class AuditLogSink(Protocol):
    """defines the persistence operation AuditLogger needs."""

    def insert(self, table_name: str, row: dict[str, Any]) -> None:
        """persists one row into the target audit table."""
        ...


class AuditLogger:
    """gives tests and future agents a minimal PostgreSQL audit sink."""

    def __init__(
        self,
        audit_sink: AuditLogSink,
        *,
        table_name: str = AUDIT_LOG_TABLE,
    ) -> None:
        """accepts a sink dependency so persistence can be mocked in tests."""
        self.audit_sink = audit_sink
        self.table_name = table_name

    def save(self, log_data: dict[str, Any]) -> None:
        """writes decisions to a single audit log table for traceability."""
        self.audit_sink.insert(self.table_name, log_data)
