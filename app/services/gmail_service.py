"""
services/gmail_service.py
==========================
All communication with the Gmail API lives here.
Routes should NEVER import googleapiclient directly — they always go through this service.

Key design decisions:
  - Returns clean Python dicts/lists, never raw API objects
  - Handles token refresh transparently
  - Pagination is handled internally via next_page_token
"""

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request as GoogleRequest
from app.utils.token_store import load_token, save_token
from app.utils.email_parser import parse_message, extract_body, get_header
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def _is_not_found_error(error: HttpError) -> bool:
    """Return True when Gmail reports the message no longer exists."""
    try:
        return error.resp.status == 404
    except Exception:
        return False


def _get_gmail_service():
    """
    Build and return an authenticated Gmail API service object.
    Automatically refreshes expired tokens.
    Raises ValueError if the user hasn't authenticated yet.
    """
    credentials = load_token()
    if not credentials:
        raise ValueError("User not authenticated. Please complete OAuth flow first.")

    # Refresh access token if it's expired
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
        save_token(credentials)  # Persist the refreshed token

    return build("gmail", "v1", credentials=credentials)


def fetch_emails(
    max_results: int = 50,
    page_token: Optional[str] = None,
    query: str = "",
) -> dict:
    """
    Fetch emails from Gmail inbox.

    Args:
        max_results:  Number of emails to return (max 500 per Gmail API limits)
        page_token:   Token for fetching the next page of results
        query:        Gmail search query string (e.g. "is:unread", "from:boss@co.com")

    Returns:
        {
          "emails": [parsed_email_dict, ...],
          "next_page_token": str | None,
          "result_size_estimate": int
        }
    """
    service = _get_gmail_service()

    # Step 1: Get list of message IDs matching the query
    list_response = service.users().messages().list(
        userId="me",
        maxResults=min(max_results, 500),
        pageToken=page_token,
        q=query or "in:inbox",
    ).execute()

    message_stubs = list_response.get("messages", [])

    if not message_stubs:
        return {"emails": [], "next_page_token": None, "result_size_estimate": 0}

    # Step 2: Fetch full metadata for each message ID
    # We use 'metadata' format to avoid downloading full bodies
    emails = []
    for stub in message_stubs:
        try:
            raw = service.users().messages().get(
                userId="me",
                id=stub["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            emails.append(parse_message(raw))
        except HttpError as e:
            logger.warning(f"Failed to fetch message {stub['id']}: {e}")
            continue

    return {
        "emails": emails,
        "next_page_token": list_response.get("nextPageToken"),
        "result_size_estimate": list_response.get("resultSizeEstimate", 0),
    }


def fetch_all_emails(
    query: str = "-in:trash",
    page_size: int = 200,
    max_pages: Optional[int] = None,
) -> dict:
    """
    Scan the full mailbox by paging through all results internally.
    Returns all collected message metadata plus a sync summary.
    """
    all_emails = []
    pages = 0
    page_token = None

    while True:
        page = fetch_emails(max_results=page_size, page_token=page_token, query=query)
        all_emails.extend(page["emails"])
        pages += 1
        page_token = page["next_page_token"]

        if not page_token or (max_pages is not None and pages >= max_pages):
            break

    return {
        "emails": all_emails,
        "pages": pages,
        "fetched": len(all_emails),
        "next_page_token": page_token,
    }


def get_email_detail(message_id: str) -> dict:
    """Fetch full message detail for a single email on demand."""
    service = _get_gmail_service()
    raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = raw.get("payload", {}).get("headers", [])
    return {
        "id": raw["id"],
        "thread_id": raw.get("threadId"),
        "subject": get_header(headers, "Subject") or "(no subject)",
        "sender": get_header(headers, "From") or "",
        "to": get_header(headers, "To") or "",
        "cc": get_header(headers, "Cc") or "",
        "date": get_header(headers, "Date") or "",
        "snippet": raw.get("snippet", ""),
        "labels": raw.get("labelIds", []),
        "body": extract_body(raw.get("payload", {})).strip(),
    }


def trash_email(message_id: str) -> bool:
    """Move a single email to trash. Returns True on success."""
    try:
        service = _get_gmail_service()
        service.users().messages().trash(userId="me", id=message_id).execute()
        return True
    except HttpError as e:
        if _is_not_found_error(e):
            logger.warning(f"Message {message_id} no longer exists in Gmail; treating as already removed.")
            return True
        logger.error(f"Failed to trash message {message_id}: {e}")
        return False


def untrash_email(message_id: str) -> bool:
    """Restore a trashed email to the mailbox."""
    try:
        service = _get_gmail_service()
        service.users().messages().untrash(userId="me", id=message_id).execute()
        return True
    except HttpError as e:
        logger.error(f"Failed to untrash message {message_id}: {e}")
        return False


def mark_as_important(message_id: str) -> bool:
    """Apply Gmail IMPORTANT and STARRED labels to an email."""
    try:
        service = _get_gmail_service()
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": ["IMPORTANT", "STARRED"]},
        ).execute()
        return True
    except HttpError as e:
        logger.error(f"Failed to mark {message_id} important: {e}")
        return False


def mark_as_read(message_id: str) -> bool:
    """Remove the UNREAD label from a message."""
    try:
        service = _get_gmail_service()
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        return True
    except HttpError as e:
        logger.error(f"Failed to mark {message_id} as read: {e}")
        return False


def batch_trash(message_ids: list[str]) -> dict:
    """
    Trash multiple emails. Returns a summary of successes and failures.
    Used by the 'one-click cleanup' feature.
    """
    service = _get_gmail_service()
    results = {"success": [], "failed": []}

    def callback(request_id, response, exception):
        message_id = request_id
        if exception is None:
            results["success"].append(message_id)
            return
        if isinstance(exception, HttpError) and _is_not_found_error(exception):
            logger.warning(f"Message {message_id} no longer exists in Gmail; treating as already removed.")
            results["success"].append(message_id)
            return
        logger.error(f"Failed to trash message {message_id}: {exception}")
        results["failed"].append(message_id)

    batch_size = 100
    for start in range(0, len(message_ids), batch_size):
        batch = service.new_batch_http_request(callback=callback)
        for message_id in message_ids[start:start + batch_size]:
            batch.add(
                service.users().messages().trash(userId="me", id=message_id),
                request_id=message_id,
            )
        batch.execute()

    return results


def batch_untrash(message_ids: list[str]) -> dict:
    """Restore multiple emails from trash."""
    service = _get_gmail_service()
    results = {"success": [], "failed": []}

    def callback(request_id, response, exception):
        message_id = request_id
        if exception is None:
            results["success"].append(message_id)
            return
        logger.error(f"Failed to untrash message {message_id}: {exception}")
        results["failed"].append(message_id)

    batch_size = 100
    for start in range(0, len(message_ids), batch_size):
        batch = service.new_batch_http_request(callback=callback)
        for message_id in message_ids[start:start + batch_size]:
            batch.add(
                service.users().messages().untrash(userId="me", id=message_id),
                request_id=message_id,
            )
        batch.execute()

    return results
