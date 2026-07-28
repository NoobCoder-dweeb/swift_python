from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import import_module
from typing import Protocol

from app.schemas.email import IncomingEmail


@dataclass(frozen=True)
class SpamAssessment:
    """captures spam signals without coupling intake to one model."""

    is_spam: bool
    score: float
    action: str
    reasons: list[str] = field(default_factory=list)
    classifier_score: float | None = None


class SpamFilter(Protocol):
    """lets email intake use rule-only or hybrid spam detection."""

    def assess(self, email: IncomingEmail) -> SpamAssessment:
        """returns an actionable spam assessment for one email."""
        ...


class HybridSpamFilter:
    """combines deterministic spam rules with an optional TF-IDF classifier."""

    def __init__(
        self,
        *,
        classifier: "TfidfSpamClassifier | None" = None,
        spam_threshold: float = 0.8,
        suspected_threshold: float = 0.5,
    ) -> None:
        """keeps thresholds injectable for tests and deployment tuning."""
        self.classifier = classifier or _default_tfidf_classifier()
        self.spam_threshold = spam_threshold
        self.suspected_threshold = suspected_threshold

    def assess(self, email: IncomingEmail) -> SpamAssessment:
        """scores spam before the sales drafting workflow spends effort."""
        text = _email_text_for_spam_scan(email)
        rule_score, reasons = _score_deterministic_spam_rules(email, text)
        classifier_score = (
            self.classifier.predict_spam_score(text)
            if self.classifier and self.classifier.available
            else None
        )
        if classifier_score is None:
            score = rule_score
        else:
            score = max(rule_score, (0.65 * classifier_score) + (0.35 * rule_score))

        score = round(min(score, 1.0), 3)
        if score >= self.spam_threshold:
            action = "block"
        elif score >= self.suspected_threshold:
            action = "review"
        else:
            action = "allow"

        return SpamAssessment(
            is_spam=action == "block",
            score=score,
            action=action,
            reasons=reasons,
            classifier_score=(
                round(classifier_score, 3)
                if classifier_score is not None
                else None
            ),
        )


class TfidfSpamClassifier:
    """small optional sklearn classifier trained from bundled examples."""

    def __init__(self, pipeline: object | None = None) -> None:
        self.pipeline = pipeline

    @property
    def available(self) -> bool:
        return self.pipeline is not None

    @classmethod
    def from_builtin_training_data(cls) -> "TfidfSpamClassifier":
        """builds a lightweight model when sklearn is installed."""
        try:
            feature_extraction = import_module("sklearn.feature_extraction.text")
            linear_model = import_module("sklearn.linear_model")
            pipeline_module = import_module("sklearn.pipeline")
        except Exception:
            return cls(None)

        examples, labels = _training_examples()
        pipeline = pipeline_module.make_pipeline(
            feature_extraction.TfidfVectorizer(
                lowercase=True,
                ngram_range=(1, 2),
                min_df=1,
            ),
            linear_model.LogisticRegression(max_iter=200),
        )
        try:
            pipeline.fit(examples, labels)
        except Exception:
            return cls(None)
        return cls(pipeline)

    def predict_spam_score(self, text: str) -> float:
        """returns spam probability, or 0 when the model is unavailable."""
        if self.pipeline is None:
            return 0.0
        if hasattr(self.pipeline, "predict_proba"):
            probabilities = self.pipeline.predict_proba([text])[0]
            classes = list(getattr(self.pipeline, "classes_", []))
            try:
                spam_index = classes.index(1)
            except ValueError:
                spam_index = len(probabilities) - 1
            return float(probabilities[spam_index])
        prediction = self.pipeline.predict([text])[0]
        return 1.0 if int(prediction) == 1 else 0.0


def _email_text_for_spam_scan(email: IncomingEmail) -> str:
    """combines sender and message text so sender patterns affect scoring."""
    return f"{email.sender}\n{email.subject}\n{email.body}".strip()


def _score_deterministic_spam_rules(
    email: IncomingEmail, text: str
) -> tuple[float, list[str]]:
    """scores obvious spam signals before the optional ML classifier runs."""
    lower = text.lower()
    body_lower = email.body.lower()
    reasons: list[str] = []
    score = 0.0

    url_count = len(re.findall(r"https?://|www\.", lower))
    if url_count >= 3:
        score += 0.35
        reasons.append("many_links")
    elif url_count:
        score += 0.12

    if _contains_any(
        lower,
        (
            "limited time offer",
            "winner",
            "claim your prize",
            "free money",
            "risk-free",
            "guaranteed income",
            "crypto investment",
            "forex signal",
            "seo backlinks",
            "casino",
            "viagra",
            "loan approved",
        ),
    ):
        score += 0.35
        reasons.append("spam_keyword")

    if re.search(r"\b(?:unsubscribe|click here|act now)\b", lower):
        score += 0.2
        reasons.append("marketing_call_to_action")

    if _uppercase_ratio(email.body) > 0.55 and len(email.body) > 40:
        score += 0.2
        reasons.append("excessive_uppercase")

    if re.search(r"(.)\1{9,}", email.body):
        score += 0.15
        reasons.append("repeated_characters")

    if _lacks_sales_product_terms(body_lower) and (
        url_count or any(reason in reasons for reason in ("spam_keyword", "marketing_call_to_action"))
    ):
        score += 0.2
        reasons.append("low_product_relevance")

    if _sender_has_suspicious_pattern(email.sender):
        score += 0.15
        reasons.append("suspicious_sender")

    return min(score, 1.0), reasons


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """keeps keyword checks readable at call sites."""
    return any(needle in text for needle in needles)


def _uppercase_ratio(value: str) -> float:
    """measures shouting-style text without counting punctuation or digits."""
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return 0.0
    uppercase = [char for char in letters if char.isupper()]
    return len(uppercase) / len(letters)


def _lacks_sales_product_terms(lower_body: str) -> bool:
    """flags messages that do not look like product, price, or stock inquiries."""
    product_terms = (
        "product",
        "price",
        "pricing",
        "quote",
        "stock",
        "availability",
        "available",
        "sku",
        "helmet",
        "glove",
        "safety",
        "unit",
        "units",
    )
    return not _contains_any(lower_body, product_terms)


def _sender_has_suspicious_pattern(sender: str) -> bool:
    """detects disposable-looking sender patterns that increase spam confidence."""
    lowered = sender.lower()
    local, _, domain = lowered.partition("@")
    if not domain:
        return True
    if re.search(r"\d{5,}", local):
        return True
    return domain.endswith((".xyz", ".top", ".click", ".loan", ".work"))


def _training_examples() -> tuple[list[str], list[int]]:
    spam = [
        "WINNER claim your prize now click here limited time offer",
        "Guaranteed income crypto investment risk-free returns act now",
        "Cheap SEO backlinks casino bonus viagra offer unsubscribe",
        "Loan approved free money visit http://spam.example http://spam2.example",
        "FOREX signals make money fast click here winner",
        "Congratulations you have been selected for a prize claim today",
    ]
    ham = [
        "Can you quote 40 units of Product X?",
        "Please confirm stock availability for safety helmets next week.",
        "Do you have Safety Gloves available and what is the price?",
        "Please list available products in eye protection.",
        "Can you provide pricing and stock for 20 face shields?",
        "I would like a quote for safety boots and delivery timing.",
    ]
    return [*spam, *ham], [*[1] * len(spam), *[0] * len(ham)]


@lru_cache(maxsize=1)
def _default_tfidf_classifier() -> TfidfSpamClassifier:
    """trains the bundled classifier once per process."""
    return TfidfSpamClassifier.from_builtin_training_data()
