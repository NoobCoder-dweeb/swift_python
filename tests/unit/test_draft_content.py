from app.services.draft_content import normalize_email_draft


def test_normalize_email_draft_removes_html_and_duplicate_signature():
    draft = """Best regards,<br>
Project Swift Support

Hi,

The 3M&trade; safety helmet is available at [https://example.com/helmet/](https://example.com/helmet/).

Best regards,<br>
Project Swift Support"""

    normalized = normalize_email_draft(draft)

    assert "<br>" not in normalized
    assert "[https://" not in normalized
    assert "3M™ safety helmet" in normalized
    assert "https://example.com/helmet/" in normalized
    assert normalized.count("Best regards,") == 1
    assert normalized.startswith("Hi,")
    assert normalized.endswith("Best regards,\nProject Swift Support")


def test_normalize_email_draft_preserves_plain_text_comparisons():
    draft = "Hi,\n\nThe requested quantity is < 100 units.\n\nBest regards,\nProject Swift Support"

    assert normalize_email_draft(draft) == draft


def test_normalize_email_draft_decodes_unicode_and_removes_agent_instructions():
    draft = (
        "Hi,\n\nThe 3M\\u2122 safety helmet is available.\n\n"
        "Best regards,\nProject Swift Support\n\n"
        "This is the expected criteria for your final answer: A concise email "
        "reply with approved facts."
    )

    normalized = normalize_email_draft(draft)

    assert "3M™ safety helmet" in normalized
    assert "\\u2122" not in normalized
    assert "expected criteria" not in normalized.lower()
    assert normalized.endswith("Best regards,\nProject Swift Support")
