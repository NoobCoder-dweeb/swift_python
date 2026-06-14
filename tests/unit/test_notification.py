import pytest


def test_sales_officer_notified_when_draft_ready(notification_service):
    """verifies generated drafts produce a review notification."""
    draft = {"id": "DRAFT-001", "content": "Dear customer..."}

    result = notification_service.notify_review_required(draft)

    assert result.sent is True
    assert result.type == "draft_review"
