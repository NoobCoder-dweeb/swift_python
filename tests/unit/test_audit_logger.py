import pytest

from app.services.audit_logger import AuditLogger


def test_decision_log_saved_to_postgres(audit_logger, mock_postgres_client):
    """protects the contract that decisions are persisted to audit_logs."""
    log_data = {"role": "system", "decision": "route", "to": "sales_processing"}

    audit_logger.save(log_data)

    mock_postgres_client.insert.assert_called_once_with("audit_logs", log_data)


def test_decision_log_table_can_be_injected(mock_postgres_client):
    """keeps AuditLogger open to alternate audit sinks without subclassing."""
    log_data = {"role": "system", "decision": "route", "to": "sales_processing"}
    audit_logger = AuditLogger(mock_postgres_client, table_name="custom_audit_logs")

    audit_logger.save(log_data)

    mock_postgres_client.insert.assert_called_once_with("custom_audit_logs", log_data)
