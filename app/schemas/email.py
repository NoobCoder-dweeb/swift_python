from pydantic import BaseModel


class IncomingEmail(BaseModel):
    """normalises all intake formats into sender, subject, and body."""

    sender: str
    subject: str
    body: str
