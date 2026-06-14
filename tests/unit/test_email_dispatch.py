import pytest


def test_email_sent_after_approval(dispatch_service, mock_email_client):
    """ensures only approved drafts are sent to customers."""
    draft = {"to": "customer@example.com", "content": "Dear customer..."}

    dispatch_service.dispatch(draft, approved=True)

    mock_email_client.send.assert_called_once()


def test_email_not_sent_when_rejected(dispatch_service, mock_email_client):
    """prevents rejected drafts from leaving the review workflow."""
    draft = {"to": "customer@example.com", "content": "Dear customer..."}

    dispatch_service.dispatch(draft, approved=False)

    mock_email_client.send.assert_not_called()
