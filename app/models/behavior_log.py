"""
models/behavior_log.py
======================
Append-only log of every user action.
This is the raw data that feeds the Behavior Engine.
Actions: "open" | "delete" | "archive" | "mark_important" | "ignore" | "unsubscribe"
"""

from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.db.database import Base


class BehaviorLog(Base):
    __tablename__ = "behavior_logs"

    id         = Column(String, primary_key=True)   # UUID generated at insert time
    email_id   = Column(String, ForeignKey("emails.id"), index=True)
    sender     = Column(String, index=True)          # Denormalised for fast aggregation
    action     = Column(String, nullable=False)      # See docstring above
    timestamp  = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_behavior_sender_action", "sender", "action"),
    )
