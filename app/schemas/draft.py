from pydantic import BaseModel


class EmailPayload(BaseModel):
    sender: str
    subject: str
    body: str


class DraftResponse(BaseModel):
    draft_id: str
    sender: str
    subject: str
    customer_inquiry: str
    ai_draft: str
    status: str
