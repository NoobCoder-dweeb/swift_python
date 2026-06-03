from pydantic import BaseModel


class IncomingEmail(BaseModel):
    sender: str
    subject: str
    body: str