"""
utils/token_store.py
====================
Simple file-based OAuth token store for MVP.
In production, replace with encrypted DB storage per user.

The token is stored as a JSON file at ./tokens/user_token.json
(gitignored). This is intentionally simple for Phase 1.
"""

import json
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from app.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TOKEN_DIR  = BACKEND_ROOT / "tokens"
TOKEN_FILE = TOKEN_DIR / "user_token.json"


def save_token(credentials: Credentials) -> None:
    """Persist OAuth credentials to disk."""
    TOKEN_DIR.mkdir(exist_ok=True)
    token_data = {
        "token":         credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri":     credentials.token_uri,
        "client_id":     credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes":        credentials.scopes,
    }
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))


def load_token() -> Credentials | None:
    """Load credentials from disk. Returns None if not found."""
    if not TOKEN_FILE.exists():
        return None
    data = json.loads(TOKEN_FILE.read_text())
    return Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id", settings.google_client_id),
        client_secret=data.get("client_secret", settings.google_client_secret),
        scopes=data.get("scopes", settings.google_scopes),
    )


def delete_token() -> None:
    """Remove stored token (used on logout)."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
