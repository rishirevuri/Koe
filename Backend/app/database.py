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
