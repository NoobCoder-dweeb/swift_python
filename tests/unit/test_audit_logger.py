import pytest


def test_decision_log_saved_to_postgres(audit_logger, mock_postgres_client):
    """Why: protects the contract that decisions are persisted to audit_logs."""
    log_data = {"role": "system", "decision": "route", "to": "sales_processing"}

    audit_logger.save(log_data)

    mock_postgres_client.insert.assert_called_once_with("audit_logs", log_data)
