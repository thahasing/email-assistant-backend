"""
api/insights.py
===============
Dashboard metrics and summary data.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services import insights_service

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    """
    Return the full dashboard summary:
    - Email counts by category
    - Top senders
    - Week-over-week change
    - Suggestions
    """
    return insights_service.get_summary(db)
