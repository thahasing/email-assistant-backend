"""
utils/email_parser.py
=====================
Parses raw Gmail API message payloads into clean Python dicts.
Gmail's payload format is deeply nested — this module hides that complexity
from the rest of the application.
"""

import re
import base64
from datetime import datetime, timezone
from typing import Optional


def extract_sender_email(sender_string: str) -> str:
    """
    Extract bare email from strings like 'John Doe <john@example.com>'
    or just 'john@example.com'.
    """
    match = re.search(r"<([^>]+)>", sender_string)
    if match:
        return match.group(1).lower().strip()
    return sender_string.lower().strip()


def parse_gmail_timestamp(internal_date: str) -> datetime:
    """
    Gmail returns internalDate as milliseconds since epoch (as a string).
    """
    ts_seconds = int(internal_date) / 1000
    return datetime.fromtimestamp(ts_seconds, tz=timezone.utc)


def get_header(headers: list[dict], name: str) -> Optional[str]:
    """Find a header value by name (case-insensitive) from Gmail headers list."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def parse_message(raw_message: dict) -> dict:
    """
    Transform a raw Gmail API message object into a flat dict
    suitable for inserting into our Email model.

    Args:
        raw_message: The dict returned by gmail.users().messages().get()

    Returns:
        Flat dict with keys: id, thread_id, subject, sender, sender_email,
                             snippet, timestamp, is_read, labels
    """
    headers = raw_message.get("payload", {}).get("headers", [])
    label_ids = raw_message.get("labelIds", [])

    sender_raw = get_header(headers, "from") or ""
    timestamp_raw = raw_message.get("internalDate", "0")

    return {
        "id":           raw_message["id"],
        "thread_id":    raw_message.get("threadId", ""),
        "subject":      get_header(headers, "subject") or "(no subject)",
        "sender":       sender_raw,
        "sender_email": extract_sender_email(sender_raw),
        "snippet":      raw_message.get("snippet", "")[:300],   # cap at 300 chars
        "timestamp":    parse_gmail_timestamp(timestamp_raw),
        "is_read":      "UNREAD" not in label_ids,
        "is_deleted":   "TRASH" in label_ids,
        "labels":       ",".join(label_ids),
    }


def _decode_body_data(data: str | None) -> str:
    """Decode a Gmail message body chunk into UTF-8 text."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
    return decoded.decode("utf-8", errors="ignore")


def extract_body(payload: dict) -> str:
    """Walk the Gmail payload tree and return the best text body available."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if body_data and mime_type == "text/plain":
        return _decode_body_data(body_data)

    if body_data and not payload.get("parts"):
        return _decode_body_data(body_data)

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            text = extract_body(part)
            if text:
                return text

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html":
            html = extract_body(part)
            if html:
                return re.sub(r"<[^>]+>", " ", html)

    for part in payload.get("parts", []):
        nested = extract_body(part)
        if nested:
            return nested

    return ""
