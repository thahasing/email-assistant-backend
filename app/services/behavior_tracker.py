"""
services/behavior_tracker.py
============================
Records user interactions with emails and updates sender importance scores.

Score update formula (exponential moving average style):
  - "open"           → +1.0
  - "mark_important" → +2.0
  - "archive"        → +0.3
  - "ignore"         → -0.5
  - "delete"         → -1.0
  - "unsubscribe"    → -2.0

Scores are clamped to [-10, +10].

The SenderScore table is the "memory" of the system. Over time,
senders the user always opens get positive scores; senders they always
delete get negative scores. The classifier then uses these scores.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.behavior_log import BehaviorLog
from app.models.sender_score import SenderScore
from app.models.email import Email
import logging

logger = logging.getLogger(__name__)

# How much each action shifts the importance score
ACTION_WEIGHTS = {
    "open":           +1.0,
    "mark_important": +2.0,
    "archive":        +0.3,
    "ignore":         -0.5,
    "delete":         -1.0,
    "unsubscribe":    -2.0,
}

SCORE_MIN = -10.0
SCORE_MAX = +10.0
LEARNING_RATE = 0.3   # How quickly new behavior overrides old score (0 = no learning, 1 = replace)


def log_action(email_id: str, action: str, db: Session) -> bool:
    """
    Record a user action and update the sender's importance score.

    Args:
        email_id: The Gmail message ID
        action:   One of the keys in ACTION_WEIGHTS
        db:       Active SQLAlchemy session

    Returns:
        True if the sender score was updated, False if the email wasn't found.
    """
    if action not in ACTION_WEIGHTS:
        logger.warning(f"Unknown action: {action}")
        return False

    # Look up the email to get the sender
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        logger.warning(f"Email {email_id} not found in DB, cannot log action.")
        return False

    if action == "open":
        email.last_opened_at = datetime.now(timezone.utc)
        email.is_read = True
    elif action == "mark_important":
        labels = set(filter(None, (email.labels or "").split(",")))
        labels.update({"IMPORTANT", "STARRED"})
        email.labels = ",".join(sorted(labels))
        email.is_cleanup_candidate = False
        email.cleanup_reason = None
    elif action == "delete":
        email.is_deleted = True
    elif action in {"archive", "ignore"}:
        email.is_cleanup_candidate = False
    db.add(email)

    # 1. Append to the behavior log (immutable audit trail)
    log_entry = BehaviorLog(
        id=str(uuid.uuid4()),
        email_id=email_id,
        sender=email.sender_email,
        action=action,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log_entry)

    # 2. Update sender score (upsert)
    _update_sender_score(email.sender_email, email.sender, action, db)

    db.commit()
    return True


def _update_sender_score(
    sender_email: str,
    display_name: str,
    action: str,
    db: Session,
) -> None:
    """
    Apply an exponential moving average update to the sender's importance score.
    Creates the record if it doesn't exist yet.
    """
    record = db.query(SenderScore).filter(
        SenderScore.sender_email == sender_email
    ).first()

    weight = ACTION_WEIGHTS.get(action, 0.0)

    if record is None:
        # First time we've seen this sender
        record = SenderScore(
            sender_email=sender_email,
            display_name=display_name,
            importance_score=weight,
            open_count=0,
            delete_count=0,
            ignore_count=0,
            total_received=0,
            last_seen=datetime.now(timezone.utc),
        )
        db.add(record)
    else:
        # Exponential moving average: new_score = old + lr * (signal - old)
        # This means frequent behavior has diminishing returns — the score
        # stabilises rather than drifting to the extremes.
        record.importance_score += LEARNING_RATE * (weight - record.importance_score * 0.1)
        record.importance_score = max(SCORE_MIN, min(SCORE_MAX, record.importance_score))
        record.last_seen = datetime.now(timezone.utc)

    # Increment the relevant counter
    if action == "open":
        record.open_count += 1
    elif action == "delete":
        record.delete_count += 1
    elif action == "ignore":
        record.ignore_count += 1

    record.total_received += 1


def get_suggestions(db: Session, threshold_ignores: int = 5) -> list[dict]:
    """
    Return a list of action suggestions based on learned behavior.
    Currently surfaces:
      - Senders with many ignores / deletes → suggest auto-delete
      - Senders with very negative scores  → suggest unsubscribe

    Args:
        db:                Active DB session
        threshold_ignores: Min ignore count to trigger a suggestion

    Returns:
        List of suggestion dicts.
    """
    suggestions = []

    # Senders the user consistently ignores or deletes
    candidates = db.query(SenderScore).filter(
        (SenderScore.ignore_count >= threshold_ignores) |
        (SenderScore.importance_score <= -3.0)
    ).order_by(SenderScore.importance_score).limit(10).all()

    for c in candidates:
        if c.ignore_count >= threshold_ignores:
            suggestions.append({
                "sender_email":  c.sender_email,
                "display_name":  c.display_name or c.sender_email,
                "suggestion":    f"You've ignored {c.ignore_count} emails from this sender. Auto-delete future emails?",
                "action":        "auto_delete",
                "confidence":    min(c.ignore_count / 20, 0.95),
            })
        elif c.importance_score <= -5.0:
            suggestions.append({
                "sender_email":  c.sender_email,
                "display_name":  c.display_name or c.sender_email,
                "suggestion":    f"This sender has a very low importance score ({c.importance_score:.1f}). Unsubscribe?",
                "action":        "unsubscribe",
                "confidence":    0.80,
            })

    return suggestions
