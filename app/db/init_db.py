"""
db/init_db.py
=============
Creates all tables on application startup.
In production you would use Alembic migrations instead.
"""

from sqlalchemy import inspect, text
from app.db.database import engine, Base
# Import models so SQLAlchemy knows about them before calling create_all
from app.models import email, classification, behavior_log, sender_score  # noqa: F401


EMAIL_COLUMN_MIGRATIONS = {
    "last_opened_at": "ALTER TABLE emails ADD COLUMN last_opened_at DATETIME",
    "is_cleanup_candidate": "ALTER TABLE emails ADD COLUMN is_cleanup_candidate BOOLEAN DEFAULT 0",
    "cleanup_reason": "ALTER TABLE emails ADD COLUMN cleanup_reason VARCHAR",
    "thread_message_count": "ALTER TABLE emails ADD COLUMN thread_message_count INTEGER DEFAULT 1",
}


def _ensure_email_columns() -> None:
    """Apply lightweight SQLite-safe column additions for new email metadata."""
    inspector = inspect(engine)
    if "emails" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("emails")}
    with engine.begin() as connection:
        for column_name, ddl in EMAIL_COLUMN_MIGRATIONS.items():
            if column_name not in existing_columns:
                connection.execute(text(ddl))


def init_db() -> None:
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(bind=engine)
    _ensure_email_columns()
    print("✔  Database tables created / verified.")
