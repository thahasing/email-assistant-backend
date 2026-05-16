"""
models/classification.py
=========================
Stores the AI/rule classification result for each email.
Keeping this separate from the Email model allows us to re-classify
emails as the model improves without touching the raw data.
"""

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.db.database import Base


class Classification(Base):
    __tablename__ = "classifications"

    id            = Column(String, primary_key=True)  # Same as email.id
    email_id      = Column(String, ForeignKey("emails.id"), unique=True, index=True)

    # Label: "important" | "promotions" | "spam" | "social" | "updates"
    label         = Column(String, nullable=False, index=True)
    confidence    = Column(Float, default=0.0)   # 0.0 – 1.0

    # Source of classification: "rules" | "ml" | "user_override"
    source        = Column(String, default="rules")
    is_overridden = Column(Boolean, default=False)  # True if user corrected us

    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())
