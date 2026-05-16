from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.config import settings
from app.utils.token_store import save_token, load_token
import requests
import os

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/login")
def login():
    try:
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={settings.google_client_id}&"
            f"redirect_uri={settings.google_redirect_uri}&"
            "response_type=code&"
            f"scope={'%20'.join(settings.google_scopes)}&"
            "access_type=offline&"
            "prompt=consent"
        )
        return RedirectResponse(url=auth_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OAuth failed: {exc}") from exc

@router.get("/callback")
def callback(code: str = None, db: Session = Depends(get_db)):
    try:
        if not code:
            raise HTTPException(status_code=400, detail="Missing code")
        
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        
        if token_response.status_code != 200:
            raise Exception(f"Token exchange failed: {token_response.text}")
        
        tokens = token_response.json()
        save_token(tokens)
        
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
