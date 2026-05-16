from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.config import settings
from google_auth_oauthlib.flow import Flow
from app.utils.token_store import save_token, load_token
import os

router = APIRouter(prefix="/auth", tags=["auth"])

def _build_flow():
    return Flow.from_client_config(
        {
            "installed": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        },
        scopes=settings.google_scopes,
        redirect_uri=settings.google_redirect_uri,
    )

@router.get("/login")
def login():
    try:
        flow = _build_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return RedirectResponse(url=auth_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OAuth failed: {exc}") from exc

@router.get("/callback")
def callback(code: str = None, state: str = None, db: Session = Depends(get_db)):
    try:
        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code")
        
        flow = _build_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials
        save_token(credentials)
        
        return RedirectResponse(url=f"{settings.frontend_url}/dashboard")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {exc}") from exc

@router.post("/logout")
def logout():
    try:
        if os.path.exists("tokens/user_token.json"):
            os.remove("tokens/user_token.json")
        return {"message": "Logged out"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Logout failed: {exc}") from exc

@router.get("/status")
def auth_status():
    try:
        token = load_token()
        return {"authenticated": token is not None}
    except:
        return {"authenticated": False}
