from app.schemas.email import IncomingEmail
from app.services.spam_filter import HybridSpamFilter, TfidfSpamClassifier


def test_hybrid_spam_filter_blocks_rule_based_spam():
    """obvious spam should be blocked before draft generation."""
    assessment = HybridSpamFilter(classifier=TfidfSpamClassifier(None)).assess(
        IncomingEmail(
            sender="winner123456@promo.xyz",
            subject="WINNER claim your prize",
            body=(
                "LIMITED TIME OFFER!!! Claim your prize now. Click here "
                "http://spam.example http://spam2.example http://spam3.example"
            ),
        )
    )

    assert assessment.is_spam is True
    assert assessment.action == "block"
    assert assessment.score >= 0.8
    assert "many_links" in assessment.reasons
    assert "spam_keyword" in assessment.reasons


def test_hybrid_spam_filter_allows_product_inquiry():
    """normal sales inquiries should pass into the drafting workflow."""
    assessment = HybridSpamFilter(classifier=TfidfSpamClassifier(None)).assess(
        IncomingEmail(
            sender="buyer@example.com",
            subject="Safety helmet stock",
            body="Can you quote 20 safety helmets and confirm stock?",
        )
    )

    assert assessment.is_spam is False
    assert assessment.action == "allow"
    assert assessment.score < 0.5


def test_tfidf_spam_classifier_scores_spam_above_ham_when_available():
    """the optional sklearn model should provide useful relative signal."""
    classifier = TfidfSpamClassifier.from_builtin_training_data()

    assert classifier.available is True
    spam_score = classifier.predict_spam_score(
        "winner claim your prize now crypto investment"
    )
    ham_score = classifier.predict_spam_score(
        "Can you quote 20 units of Safety Helmet?"
    )

    assert spam_score > ham_score
