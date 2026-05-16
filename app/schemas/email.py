"""
schemas/email.py
================
Pydantic models that define the shape of data going IN and OUT of the API.
These are separate from the SQLAlchemy ORM models intentionally —
we control exactly what fields are exposed to the frontend.
"""

from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class EmailBase(BaseModel):
    id: str
    subject: Optional[str] = None
    sender: str
    sender_email: str
    snippet: Optional[str] = None
    timestamp: datetime
    is_read: bool = False


class EmailResponse(EmailBase):
    """Full email record returned to frontend, including classification."""
    label: Optional[str] = None        # Injected from Classification table
    confidence: Optional[float] = None
    last_opened_at: Optional[datetime] = None
    is_cleanup_candidate: bool = False
    cleanup_reason: Optional[str] = None
    mailbox: Optional[str] = None

    model_config = {"from_attributes": True}


class EmailListResponse(BaseModel):
    """Paginated list response."""
    emails: list[EmailResponse]
    total: int
    page: int
    page_size: int
    next_page_token: Optional[str] = None


class EmailDetailResponse(BaseModel):
    id: str
    thread_id: Optional[str] = None
    subject: str
    sender: str
    sender_email: str
    snippet: Optional[str] = None
    timestamp: datetime
    body: str
    to: Optional[str] = None
    cc: Optional[str] = None
    date: Optional[str] = None
    labels: list[str] = []
    label: Optional[str] = None
    confidence: Optional[float] = None


class CleanupCandidateResponse(EmailResponse):
    reason: str
    days_since_open: Optional[int] = None


class CleanupListResponse(BaseModel):
    emails: list[CleanupCandidateResponse]
    count: int
    days: int
    sync_summary: Optional[dict] = None


class BulkEmailActionRequest(BaseModel):
    email_ids: list[str]


class AssistantCommandRequest(BaseModel):
    message: str


class AssistantCommandResponse(BaseModel):
    reply: str
    action: Optional[str] = None
    metadata: dict = {}
