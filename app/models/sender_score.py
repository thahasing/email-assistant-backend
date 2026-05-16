"""
models/sender_score.py
======================
Learned importance score per sender.
Updated incrementally every time a behavior event is logged.
Score range: -10 (always spam/ignored) to +10 (always important/opened).
"""

from sqlalchemy import Column, String, Float, Integer, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class SenderScore(Base):
    __tablename__ = "sender_scores"

    sender_email  = Column(String, primary_key=True)
    display_name  = Column(String, nullable=True)

    # Computed scores
    importance_score = Column(Float, default=0.0)   # -10 to +10
    open_count       = Column(Integer, default=0)
    delete_count     = Column(Integer, default=0)
    ignore_count     = Column(Integer, default=0)
    total_received   = Column(Integer, default=0)

    last_seen   = Column(DateTime(timezone=True), nullable=True)
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
