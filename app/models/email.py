"""
models/email.py
===============
Stores email metadata fetched from Gmail.
We deliberately avoid storing full email bodies to keep the DB lightweight.
"""

from sqlalchemy import Column, String, DateTime, Boolean, Text, Index, Integer
from sqlalchemy.sql import func
from app.db.database import Base


class Email(Base):
    __tablename__ = "emails"

    id           = Column(String, primary_key=True)   # Gmail message ID
    thread_id    = Column(String, index=True)
    subject      = Column(String, nullable=True)
    sender       = Column(String, index=True)          # "Name <email@example.com>"
    sender_email = Column(String, index=True)          # Extracted email address only
    snippet      = Column(Text, nullable=True)         # First ~150 chars of body
    timestamp    = Column(DateTime(timezone=True))
    is_read      = Column(Boolean, default=False)
    is_deleted   = Column(Boolean, default=False)
    labels       = Column(String, nullable=True)       # Raw Gmail labels, comma-joined
    last_opened_at = Column(DateTime(timezone=True), nullable=True)
    is_cleanup_candidate = Column(Boolean, default=False, index=True)
    cleanup_reason = Column(String, nullable=True)
    thread_message_count = Column(Integer, default=1)

    # Audit
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_emails_timestamp", "timestamp"),
    )
