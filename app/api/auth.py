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
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={settings.google_client_id}&redirect_uri={settings.google_redirect_uri}&response_type=code&scope=https://www.googleapis.com/auth/gmail.readonly%20https://www.googleapis.com/auth/gmail.modify&access_type=offline&prompt=consent"
    return RedirectResponse(url=auth_url)

@router.get("/callback")
def callback(code: str = None, db: Session = Depends(get_db)):
    try:
        if not code:
            raise Exception("No code")
        
        resp = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code"
        })
        
        if resp.status_code != 200:
            raise Exception(resp.text)
        
        tokens = resp.json()
        save_token(tokens)
        return RedirectResponse(url=f"{settings.frontend_url}/dashboard")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/logout")
def logout():
    if os.path.exists("tokens/user_token.json"):
        os.remove("tokens/user_token.json")
    return {"ok": True}

@router.get("/status")
def status():
    return {"authenticated": load_token() is not None}
