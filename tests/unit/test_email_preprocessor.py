from app.schemas.email import IncomingEmail
from app.services.email_preprocessor import (
    EmailPreprocessor,
    FilteredEmailLines,
    preprocess_email,
)


def test_preprocess_email_removes_noise_and_keeps_inquiry_lines():
    """protects the public function API used by services and crews."""
    email = IncomingEmail(
        sender="customer@example.com",
        subject="Safety helmet pricing",
        body=(
            "Hi team,\r\n"
            "I hope you are well.\r\n"
            "Can you share pricing for 40 safety helmets?\r\n"
            "Please confirm stock availability next week.\r\n"
            "Thanks,\r\n"
            "Phone: +60 12 345 6789\r\n"
        ),
    )

    result = preprocess_email(email)

    assert result.changed is True
    assert result.email.body == (
        "Can you share pricing for 40 safety helmets?\n"
        "Please confirm stock availability next week."
    )
    assert "Hi team," in result.removed_lines
    assert "Thanks," in result.removed_lines


def test_email_preprocessor_accepts_focused_collaborators():
    """keeps cleanup and line selection replaceable without changing callers."""

    class NoiseFilter:
        def remove(self, body):
            assert body == "keep\nremove"
            return FilteredEmailLines(kept=["keep", "remove"], removed=["noise"])

    class RelevanceSelector:
        def select(self, lines):
            assert lines == ["keep", "remove"]
            return ["keep"]

    email = IncomingEmail(
        sender="customer@example.com",
        subject="Request",
        body="keep\r\nremove",
    )
    preprocessor = EmailPreprocessor(
        noise_filter=NoiseFilter(),
        relevance_selector=RelevanceSelector(),
    )

    result = preprocessor.preprocess(email)

    assert result.email.body == "keep"
    assert result.removed_lines == ["noise"]
