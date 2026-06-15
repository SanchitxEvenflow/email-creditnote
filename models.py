from typing import List
from pydantic import BaseModel


class DownloadRequest(BaseModel):
    credit_note_numbers: List[str]


class EmailRequest(BaseModel):
    credit_note_numbers: List[str]
    to_email: str
    subject: str = "Credit Notes"
    body: str = "Please find the credit note PDFs attached."


class EmailResponse(BaseModel):
    to: str
    sent_count: int
    emails_sent: int
    failed: List[dict]
