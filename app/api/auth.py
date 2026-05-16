"""
api/auth.py
===========
Handles the Google OAuth 2.0 flow.

Flow:
  1. Frontend hits GET /auth/login  → redirects to Google consent screen
  2. Google redirects to GET /auth/callback?code=...
  3. We exchange the code for tokens, save them, redirect to frontend
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.auth.exceptions import GoogleAuthError
from app.config import settings
from app.utils.token_store import save_token, delete_token
import os

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Allow HTTP for local development (OAuth normally requires HTTPS)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _oauth_configured() -> bool:
    """Return True when non-placeholder Google OAuth credentials are present."""
    placeholders = {"", "your_google_client_id_here", "your_google_client_secret_here"}
    return (
        settings.google_client_id not in placeholders
        and settings.google_client_secret not in placeholders
    )


def _build_flow() -> Flow:
    """Create the OAuth flow object from our credentials."""
    if not _oauth_configured():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env.",
        )
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id":     settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=settings.google_scopes,
        redirect_uri=settings.google_redirect_uri,
    )


@router.get("/login")
def login():
    """
    Step 1: Generate the Google OAuth URL and redirect the user to it.
    The `access_type=offline` param ensures we get a refresh_token.
    """
    try:
        flow = _build_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",  # Force consent screen so we always get refresh_token
        )
        return RedirectResponse(url=auth_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start Google OAuth flow: {exc}",
        ) from exc


@router.get("/callback")
def callback(code: str, state: str | None = None):
    """
    Step 2: Google redirects here after the user consents.
    We exchange the authorization code for access + refresh tokens.
    """
    try:
        flow = _build_flow()
        flow.fetch_token(code=code)
        save_token(flow.credentials)
    except HTTPException:
        raise
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Google OAuth failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"OAuth callback failed: {exc}",
        ) from exc

    # Redirect user back to the React app with an explicit auth-success signal.
    return RedirectResponse(url=f"{settings.frontend_url}/dashboard?auth=success")


@router.post("/logout")
def logout():
    """Delete stored token and redirect to login."""
    delete_token()
    return {"message": "Logged out successfully."}


@router.get("/status")
def auth_status():
    """Check if a token file exists (user is logged in)."""
    from app.utils.token_store import load_token
    creds = load_token()
    return {"authenticated": creds is not None}
