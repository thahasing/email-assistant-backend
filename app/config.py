"""
config.py
=========
Central configuration using Pydantic BaseSettings.
All values are read from environment variables (or .env file).
Import `settings` anywhere in the app — never read os.environ directly.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Google OAuth 2.0
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/callback"

    # Gmail scopes required by our app
    google_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]

    # Application
    secret_key: str = "changeme"
    frontend_url: str = "http://localhost:5173"
    database_url: str = "sqlite:///./email_assistant.db"
    environment: str = "development"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()  # Singleton — settings object is created once and reused
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
