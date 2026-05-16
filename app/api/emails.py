"""
api/emails.py
=============
Email sync, cleanup, and detail routes.
"""

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.classification import Classification
from app.models.email import Email
from app.schemas.email import (
    AssistantCommandRequest,
    AssistantCommandResponse,
    BulkEmailActionRequest,
    CleanupCandidateResponse,
    CleanupListResponse,
    EmailDetailResponse,
    EmailListResponse,
    EmailResponse,
)
from app.services import gmail_service
from app.services.behavior_tracker import log_action
from app.services.classifier import classify_email
from app.utils.email_parser import extract_sender_email

router = APIRouter(prefix="/emails", tags=["Emails"])

FULL_MAILBOX_QUERY = "-in:trash"


def _has_label(email: Email, label: str) -> bool:
    return label in set(filter(None, (email.labels or "").split(",")))


def _coerce_utc(value: datetime | None) -> datetime | None:
    """Normalize datetimes so SQLite naive values remain comparable."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mailbox_for_email(email: Email) -> str:
    labels = set(filter(None, (email.labels or "").split(",")))
    if "TRASH" in labels or email.is_deleted:
        return "trash"
    if "SPAM" in labels:
        return "spam"
    if "DRAFT" in labels:
        return "drafts"
    if "SENT" in labels:
        return "sent"
    return "inbox"


def _serialize_email(email: Email, clf: Classification | None) -> EmailResponse:
    return EmailResponse(
        id=email.id,
        subject=email.subject,
        sender=email.sender,
        sender_email=email.sender_email,
        snippet=email.snippet,
        timestamp=email.timestamp,
        is_read=email.is_read,
        label=clf.label if clf else None,
        confidence=clf.confidence if clf else None,
        last_opened_at=email.last_opened_at,
        is_cleanup_candidate=bool(email.is_cleanup_candidate),
        cleanup_reason=email.cleanup_reason,
        mailbox=_mailbox_for_email(email),
    )


def _upsert_email_record(email_data: dict, db: Session) -> tuple[Email, bool]:
    existing = db.query(Email).filter(Email.id == email_data["id"]).first()
    created = False

    if existing:
        for key, value in email_data.items():
            if key in {"last_opened_at", "is_cleanup_candidate", "cleanup_reason", "thread_message_count"}:
                continue
            setattr(existing, key, value)
        email = existing
    else:
        email = Email(**email_data)
        db.add(email)
        created = True

    return email, created


def _ensure_classification(email_data: dict, email_id: str, db: Session) -> Classification:
    existing = db.query(Classification).filter(Classification.email_id == email_id).first()
    if existing:
        return existing

    clf = classify_email(email_data, db=db)
    classification = Classification(
        id=str(uuid.uuid4()),
        email_id=email_id,
        label=clf.label,
        confidence=clf.confidence,
        source=clf.source,
    )
    db.add(classification)
    return classification


def _sync_thread_counts(db: Session) -> None:
    rows = (
        db.query(Email.thread_id, func.count(Email.id))
        .filter(Email.thread_id.is_not(None), Email.thread_id != "")
        .group_by(Email.thread_id)
        .all()
    )
    counts = {thread_id: count for thread_id, count in rows}
    for email in db.query(Email).all():
        email.thread_message_count = counts.get(email.thread_id, 1)


def _mark_cleanup_candidates(db: Session, days: int) -> list[tuple[Email, Classification | None]]:
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(Email, Classification)
        .outerjoin(Classification, Email.id == Classification.email_id)
        .filter(Email.is_deleted == False)
        .all()
    )

    latest_by_thread = {}
    for email, _ in rows:
        if not email.thread_id:
            continue
        latest = latest_by_thread.get(email.thread_id)
        email_timestamp = _coerce_utc(email.timestamp)
        if latest is None or (email_timestamp and email_timestamp > latest):
            latest_by_thread[email.thread_id] = email_timestamp

    candidates = []
    for email, classification in rows:
        labels = set(filter(None, (email.labels or "").split(",")))
        last_activity = _coerce_utc(email.last_opened_at or email.timestamp)
        thread_latest = latest_by_thread.get(email.thread_id, _coerce_utc(email.timestamp))
        classification_label = classification.label if classification else None

        recent_thread = bool(thread_latest and thread_latest >= threshold and email.thread_message_count > 1)
        is_inactive = bool(last_activity and last_activity < threshold)
        is_protected = "STARRED" in labels or "IMPORTANT" in labels or classification_label == "important"
        excluded_mailbox = "TRASH" in labels or "SPAM" in labels or "DRAFT" in labels

        if is_inactive and not is_protected and not recent_thread and not excluded_mailbox:
            email.is_cleanup_candidate = True
            email.cleanup_reason = f"Inactive for {days}+ days and not starred or in an active thread"
            candidates.append((email, classification))
        else:
            email.is_cleanup_candidate = False
            email.cleanup_reason = None

    return candidates


def _serialize_cleanup_email(
    email: Email,
    clf: Classification | None,
    days: int,
) -> CleanupCandidateResponse:
    last_activity = email.last_opened_at or email.timestamp
    days_since_open = None
    if last_activity:
        delta = datetime.now(timezone.utc) - _coerce_utc(last_activity)
        days_since_open = max(delta.days, 0)

    return CleanupCandidateResponse(
        **_serialize_email(email, clf).model_dump(),
        reason=email.cleanup_reason or f"Inactive for {days}+ days",
        days_since_open=days_since_open,
    )


def _full_sync(db: Session, page_size: int = 200) -> dict:
    try:
        result = gmail_service.fetch_all_emails(query=FULL_MAILBOX_QUERY, page_size=page_size)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    synced = 0
    for email_data in result["emails"]:
        email, created = _upsert_email_record(email_data, db)
        if created:
            synced += 1
        _ensure_classification(email_data, email.id, db)

    _sync_thread_counts(db)
    db.commit()

    return {
        "fetched": result["fetched"],
        "new": synced,
        "pages": result["pages"],
    }


@router.post("/sync")
def sync_emails(
    max_results: int = Query(50, ge=1, le=200),
    full_scan: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Sync either a page-sized slice or the full mailbox."""
    if full_scan:
        summary = _full_sync(db)
        return {**summary, "next_page_token": None}

    try:
        result = gmail_service.fetch_emails(max_results=max_results, query="in:inbox")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    synced = 0
    for email_data in result["emails"]:
        email, created = _upsert_email_record(email_data, db)
        if created:
            synced += 1
        _ensure_classification(email_data, email.id, db)

    _sync_thread_counts(db)
    db.commit()

    return {
        "fetched": len(result["emails"]),
        "new": synced,
        "next_page_token": result["next_page_token"],
    }


@router.get("", response_model=EmailListResponse)
def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    label: str | None = Query(None),
    mailbox: str = Query("inbox"),
    db: Session = Depends(get_db),
):
    """List stored emails with mailbox and label filters."""
    query = (
        db.query(Email, Classification)
        .outerjoin(Classification, Email.id == Classification.email_id)
    )

    if mailbox == "trash":
        query = query.filter((Email.labels.like("%TRASH%")) | (Email.is_deleted == True))
    else:
        query = query.filter(Email.is_deleted == False)
        if mailbox == "inbox":
            query = query.filter(
                ~Email.labels.like("%SENT%"),
                ~Email.labels.like("%DRAFT%"),
                ~Email.labels.like("%SPAM%"),
                ~Email.labels.like("%TRASH%"),
            )
        elif mailbox == "sent":
            query = query.filter(Email.labels.like("%SENT%"))
        elif mailbox == "drafts":
            query = query.filter(Email.labels.like("%DRAFT%"))
        elif mailbox == "spam":
            query = query.filter(Email.labels.like("%SPAM%"))

    if label:
        query = query.filter(Classification.label == label)

    total = query.count()
    rows = (
        query.order_by(Email.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    emails = [_serialize_email(email, clf) for email, clf in rows]
    return EmailListResponse(emails=emails, total=total, page=page, page_size=page_size)


@router.get("/cleanup-candidates", response_model=CleanupListResponse)
def cleanup_candidates(
    days: int = Query(7, ge=1, le=90),
    force_rescan: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Scan the full mailbox and return all cleanup candidates."""
    sync_summary = None
    if force_rescan or db.query(func.count(Email.id)).scalar() == 0:
        sync_summary = _full_sync(db)

    candidates = _mark_cleanup_candidates(db, days)
    db.commit()

    serialized = [
        _serialize_cleanup_email(email, clf, days)
        for email, clf in sorted(
            candidates,
            key=lambda row: _coerce_utc(row[0].timestamp) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    ]

    return CleanupListResponse(
        emails=serialized,
        count=len(serialized),
        days=days,
        sync_summary=sync_summary,
    )


@router.get("/{email_id}", response_model=EmailDetailResponse)
def get_email(email_id: str, db: Session = Depends(get_db)):
    """Return stored metadata plus live Gmail body content for one email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    classification = db.query(Classification).filter(Classification.email_id == email_id).first()

    try:
        detail = gmail_service.get_email_detail(email_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    log_action(email_id=email_id, action="open", db=db)
    refreshed = db.query(Email).filter(Email.id == email_id).first()

    return EmailDetailResponse(
        id=email.id,
        thread_id=email.thread_id,
        subject=detail["subject"],
        sender=detail["sender"],
        sender_email=extract_sender_email(detail["sender"]),
        snippet=detail["snippet"],
        timestamp=refreshed.timestamp,
        body=detail["body"] or detail["snippet"],
        to=detail["to"],
        cc=detail["cc"],
        date=detail["date"],
        labels=detail["labels"],
        label=classification.label if classification else None,
        confidence=classification.confidence if classification else None,
    )


@router.delete("/{email_id}")
def delete_email(email_id: str, db: Session = Depends(get_db)):
    """Trash an email both in Gmail and in the local DB."""
    success = gmail_service.trash_email(email_id)
    if success:
        email = db.query(Email).filter(Email.id == email_id).first()
        if email:
            labels = set(filter(None, (email.labels or "").split(",")))
            labels.add("TRASH")
            email.labels = ",".join(sorted(labels))
            email.is_deleted = True
            email.is_cleanup_candidate = False
            email.cleanup_reason = None
            db.add(email)
            db.commit()
        log_action(email_id=email_id, action="delete", db=db)
    return {"success": success}


@router.post("/{email_id}/restore")
def restore_email(email_id: str, db: Session = Depends(get_db)):
    """Restore a trashed email."""
    success = gmail_service.untrash_email(email_id)
    if success:
        email = db.query(Email).filter(Email.id == email_id).first()
        if email:
            labels = set(filter(None, (email.labels or "").split(",")))
            labels.discard("TRASH")
            email.labels = ",".join(sorted(labels))
            email.is_deleted = False
            email.is_cleanup_candidate = False
            email.cleanup_reason = None
            db.add(email)
            db.commit()
    return {"success": success}


@router.post("/{email_id}/important")
def mark_important(email_id: str, db: Session = Depends(get_db)):
    """Star and protect an email from cleanup."""
    success = gmail_service.mark_as_important(email_id)
    if success:
        email = db.query(Email).filter(Email.id == email_id).first()
        if email:
            labels = set(filter(None, (email.labels or "").split(",")))
            labels.update({"IMPORTANT", "STARRED"})
            email.labels = ",".join(sorted(labels))
            email.is_cleanup_candidate = False
            email.cleanup_reason = None
            db.add(email)
            db.commit()
        log_action(email_id=email_id, action="mark_important", db=db)
    return {"success": success}


@router.post("/bulk-delete")
def bulk_delete(body: BulkEmailActionRequest, db: Session = Depends(get_db)):
    """Trash multiple emails."""
    result = gmail_service.batch_trash(body.email_ids)
    if result["success"]:
        emails = db.query(Email).filter(Email.id.in_(result["success"])).all()
        for email in emails:
            labels = set(filter(None, (email.labels or "").split(",")))
            labels.add("TRASH")
            email.labels = ",".join(sorted(labels))
            email.is_deleted = True
            email.is_cleanup_candidate = False
            email.cleanup_reason = None
            db.add(email)
        db.commit()
    return result


@router.post("/delete-cleanup-candidates")
def delete_cleanup_candidates(db: Session = Depends(get_db)):
    """Trash every email currently marked as a cleanup candidate."""
    candidate_ids = [
        email_id
        for (email_id,) in db.query(Email.id).filter(Email.is_cleanup_candidate == True).all()
    ]

    if not candidate_ids:
        return {"success": [], "failed": [], "count": 0}

    result = gmail_service.batch_trash(candidate_ids)
    if result["success"]:
        emails = db.query(Email).filter(Email.id.in_(result["success"])).all()
        for email in emails:
            labels = set(filter(None, (email.labels or "").split(",")))
            labels.add("TRASH")
            email.labels = ",".join(sorted(labels))
            email.is_deleted = True
            email.is_cleanup_candidate = False
            email.cleanup_reason = None
            db.add(email)
        db.commit()

    return {
        "success": result["success"],
        "failed": result["failed"],
        "count": len(candidate_ids),
    }


@router.post("/bulk-restore")
def bulk_restore(body: BulkEmailActionRequest, db: Session = Depends(get_db)):
    """Restore multiple emails from trash."""
    result = gmail_service.batch_untrash(body.email_ids)
    if result["success"]:
        emails = db.query(Email).filter(Email.id.in_(result["success"])).all()
        for email in emails:
            labels = set(filter(None, (email.labels or "").split(",")))
            labels.discard("TRASH")
            email.labels = ",".join(sorted(labels))
            email.is_deleted = False
            email.is_cleanup_candidate = False
            email.cleanup_reason = None
            db.add(email)
        db.commit()
    return result


@router.post("/assistant/command", response_model=AssistantCommandResponse)
def assistant_command(body: AssistantCommandRequest, db: Session = Depends(get_db)):
    """Simple command layer for the persistent assistant panel."""
    message = body.message.strip().lower()

    if not message:
        return AssistantCommandResponse(reply="Ask me to explain selections, filter mail, scan inactive emails, or undo actions.")

    if "why" in message and "selected" in message:
        candidates = _mark_cleanup_candidates(db, 7)
        db.commit()
        return AssistantCommandResponse(
            reply=(
                f"I selected {len(candidates)} emails because they were inactive for more than 7 days, "
                "not starred or marked important, and not part of recently active threads."
            ),
            action="explain_cleanup",
            metadata={"count": len(candidates)},
        )

    if "promotional" in message or "promotions" in message:
        return AssistantCommandResponse(
            reply="Filtering the mailbox to promotional emails.",
            action="filter_label",
            metadata={"label": "promotions", "mailbox": "inbox"},
        )

    if "clean all inactive" in message or "scan inactive" in message:
        candidates = _mark_cleanup_candidates(db, 7)
        db.commit()
        return AssistantCommandResponse(
            reply=f"Full mailbox scan complete. {len(candidates)} inactive emails are ready for review in Selected for Deletion.",
            action="open_cleanup",
            metadata={"count": len(candidates)},
        )

    if "show selected" in message:
        return AssistantCommandResponse(
            reply="Opening the Selected for Deletion workspace.",
            action="open_cleanup",
            metadata={},
        )

    if "undo" in message:
        return AssistantCommandResponse(
            reply="I can reverse the last bulk delete or restore from the dashboard history.",
            action="undo",
            metadata={},
        )

    if "delete all" in message:
        candidate_ids = [
            email_id for (email_id,) in db.query(Email.id).filter(Email.is_cleanup_candidate == True).all()
        ]
        return AssistantCommandResponse(
            reply=f"Ready to move {len(candidate_ids)} cleanup candidates to trash.",
            action="bulk_delete_cleanup",
            metadata={"count": len(candidate_ids), "email_ids": candidate_ids},
        )

    if "restore all" in message:
        candidate_ids = [
            email_id for (email_id,) in db.query(Email.id).filter(Email.is_cleanup_candidate == True).all()
        ]
        return AssistantCommandResponse(
            reply=f"Ready to restore {len(candidate_ids)} cleanup candidates.",
            action="bulk_restore_cleanup",
            metadata={"count": len(candidate_ids), "email_ids": candidate_ids},
        )

    return AssistantCommandResponse(
        reply="I can explain why emails were selected, show promotional mail, scan inactive emails, open the cleanup view, or prepare bulk delete and restore actions.",
        action="help",
        metadata={},
    )
