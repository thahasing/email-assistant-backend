"""
api/behavior.py
===============
Endpoints for logging user actions and fetching suggestions.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services import behavior_tracker
from app.schemas.behavior import BehaviorLogRequest, BehaviorLogResponse

router = APIRouter(prefix="/behavior", tags=["Behavior"])


@router.post("/log", response_model=BehaviorLogResponse)
def log_behavior(body: BehaviorLogRequest, db: Session = Depends(get_db)):
    """
    Log a user action (open, delete, ignore, etc.) for an email.
    Automatically updates the sender's importance score.
    """
    updated = behavior_tracker.log_action(
        email_id=body.email_id,
        action=body.action,
        db=db,
    )
    return BehaviorLogResponse(logged=True, sender_score_updated=updated)


@router.get("/suggestions")
def get_suggestions(db: Session = Depends(get_db)):
    """Return AI-generated suggestions based on learned behavior patterns."""
    suggestions = behavior_tracker.get_suggestions(db)
    return {"suggestions": suggestions}
