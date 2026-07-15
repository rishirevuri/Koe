from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_count_session_columns()
    _ensure_count_entry_columns()


def ensure_count_entry_columns() -> None:
    _ensure_count_entry_columns()


def _ensure_count_session_columns() -> None:
    """Lightweight migration: add the ``exported`` column to an existing
    count_sessions table. ``create_all`` only creates missing tables, so a
    database created before this column existed needs an in-place ALTER."""
    inspector = inspect(engine)
    if "count_sessions" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("count_sessions")}
    if "exported" not in existing:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE count_sessions ADD COLUMN exported BOOLEAN NOT NULL DEFAULT 0")
            )


def _ensure_count_entry_columns() -> None:
    """Add tester count-entry fields to existing databases.

    The app still keeps older columns for compatibility, but API responses and
    exports use these lean inventory-cleaning fields.
    """
    inspector = inspect(engine)
    if "count_entries" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("count_entries")}
    column_sql = {
        "item_name_raw": "ALTER TABLE count_entries ADD COLUMN item_name_raw VARCHAR(255)",
        "category": "ALTER TABLE count_entries ADD COLUMN category VARCHAR(120)",
        "status": "ALTER TABLE count_entries ADD COLUMN status VARCHAR(80) NOT NULL DEFAULT 'Clean'",
        "original_phrase": "ALTER TABLE count_entries ADD COLUMN original_phrase TEXT",
        "counted_by": "ALTER TABLE count_entries ADD COLUMN counted_by VARCHAR(255)",
    }
    with engine.begin() as connection:
        for column, statement in column_sql.items():
            if column not in existing:
                connection.execute(text(statement))
