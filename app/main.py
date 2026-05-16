"""
main.py
=======
FastAPI application entry point.
Registers all routers, configures CORS, and initialises the database on startup.

To run:  uvicorn app.main:app --reload  (from the backend/ directory)
Docs at: http://localhost:8000/docs
"""

import fastapi
import fastapi.middleware.cors
from app.config import settings
from app.db.init_db import init_db
from app.api import auth, emails, behavior, insights

app = fastapi.FastAPI(
    title="AI Email Assistant API",
    version="1.0.0",
    description="Backend for the AI-Powered Personal Email Assistant",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow the React dev server to talk to the API without CORS errors
app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"
app.include_router(auth.router,     prefix=API_PREFIX)
app.include_router(emails.router,   prefix=API_PREFIX)
app.include_router(behavior.router, prefix=API_PREFIX)
app.include_router(insights.router, prefix=API_PREFIX)


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    """Create DB tables when the server starts (idempotent)."""
    init_db()


@app.get("/health")
def health_check():
    """Simple health check — used by load balancers and Docker healthchecks."""
    return {"status": "ok", "version": "1.0.0"}
