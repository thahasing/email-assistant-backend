"""
services/insights_service.py
============================
Aggregates data from all tables to produce dashboard metrics.
All queries here are read-only — no data is modified.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta, timezone
from app.models.email import Email
from app.models.classification import Classification
from app.models.sender_score import SenderScore
from app.services.behavior_tracker import get_suggestions


def get_summary(db: Session) -> dict:
    """Return the full dashboard summary."""
    # Total email count
    total = db.query(func.count(Email.id)).scalar() or 0
    unread = db.query(func.count(Email.id)).filter(Email.is_read == False).scalar() or 0

    # Count by classification label
    label_counts = dict(
        db.query(Classification.label, func.count(Classification.email_id))
        .group_by(Classification.label)
        .all()
    )

    cleanup_candidates = db.query(func.count(Email.id)).filter(Email.is_cleanup_candidate == True).scalar() or 0
    stale_unopened = db.query(func.count(Email.id)).filter(
        Email.is_deleted == False,
        Email.is_cleanup_candidate == True,
    ).scalar() or 0

    # Top 10 senders by total received
    top_senders = (
        db.query(SenderScore)
        .order_by(SenderScore.total_received.desc())
        .limit(10)
        .all()
    )

    top_senders_list = [
        {
            "sender_email":    s.sender_email,
            "display_name":    s.display_name or s.sender_email,
            "total_received":  s.total_received,
            "importance_score": round(s.importance_score, 2),
            "open_rate": round(s.open_count / s.total_received, 2) if s.total_received else 0,
        }
        for s in top_senders
    ]

    # Week-over-week volume change
    now     = datetime.now(timezone.utc)
    one_week_ago  = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    this_week  = db.query(func.count(Email.id)).filter(Email.timestamp >= one_week_ago).scalar() or 0
    last_week  = db.query(func.count(Email.id)).filter(
        and_(Email.timestamp >= two_weeks_ago, Email.timestamp < one_week_ago)
    ).scalar() or 0
    wow_change = ((this_week - last_week) / last_week * 100) if last_week > 0 else 0.0

    # Pull suggestions from behavior tracker
    suggestions = get_suggestions(db)

    return {
        "total_emails":       total,
        "unread":             unread,
        "important":          label_counts.get("important", 0),
        "promotions":         label_counts.get("promotions", 0),
        "spam":               label_counts.get("spam", 0),
        "social":             label_counts.get("social", 0),
        "updates":            label_counts.get("updates", 0),
        "cleanup_candidates": cleanup_candidates,
        "stale_unopened":     stale_unopened,
        "top_senders":        top_senders_list,
        "suggestions":        suggestions,
        "week_over_week_change": round(wow_change, 1),
    }
