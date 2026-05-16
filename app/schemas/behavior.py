from pydantic import BaseModel
from typing import Literal
from datetime import datetime


class BehaviorLogRequest(BaseModel):
    email_id: str
    action: Literal["open", "delete", "archive", "mark_important", "ignore", "unsubscribe"]


class BehaviorLogResponse(BaseModel):
    logged: bool
    sender_score_updated: bool


class SuggestionItem(BaseModel):
    sender_email: str
    display_name: str | None
    suggestion: str          # e.g. "Auto-delete? You've ignored 14 emails from this sender."
    action: str              # "auto_delete" | "unsubscribe"
    confidence: float


class InsightsSummary(BaseModel):
    total_emails: int
    important: int
    promotions: int
    spam: int
    unread: int
    top_senders: list[dict]
    suggestions: list[SuggestionItem]
    week_over_week_change: float  # % change in total volume
