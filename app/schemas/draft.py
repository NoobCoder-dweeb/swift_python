from pydantic import BaseModel


class EmailPayload(BaseModel):
    """defines the minimum customer inquiry needed to generate a draft."""

    sender: str
    subject: str
    body: str


class DraftResponse(BaseModel):
    """returns only the review-facing fields clients need after generation."""

    draft_id: str
    sender: str
    subject: str
    customer_inquiry: str
    ai_draft: str
    status: str
