from collections.abc import Generator
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


logger = logging.getLogger("app.database")


def _log_database_configuration(raw_url: str, effective_url: str) -> None:
    """Print, at startup (before any DB connection is opened), exactly which
    database config the app resolved. This is diagnostic-only: it NEVER prints
    the password, just whether one is present and its length. Safe to keep on.
    """
    env_value = os.getenv("DATABASE_URL")
    default_value = type(settings).model_fields["database_url"].default
    if env_value is not None:
        source = "DATABASE_URL os-environment variable (e.g. Render dashboard)"
    elif settings.database_url != default_value:
        source = "DATABASE_URL from a .env file (NOT an os-environment variable)"
    else:
        source = "hardcoded Field default in config.py (no DATABASE_URL set anywhere)"

    try:
        parsed = urlsplit(effective_url)
        username = parsed.username
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            port = "<unparseable>"
        database = parsed.path.lstrip("/") or None
        password = parsed.password
    except Exception as exc:  # pragma: no cover - defensive: never block startup on logging
        logger.warning("koe.db-config could not parse database URL: %s", exc)
        return

    raw_scheme = urlsplit(raw_url).scheme
    effective_scheme = parsed.scheme

    # PG* libpq environment variables are read by psycopg/libpq at connect time.
    # Explicit URL parameters override them, but surfacing their presence rules
    # out interference from a stray PGUSER/PGPASSWORD in the deploy environment.
    pg_env_present = {
        name: (name in os.environ) for name in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "PGDATABASE", "PGSSLMODE")
    }

    lines = [
        "koe.db-config ==================================================",
        f"koe.db-config source            : {source}",
        f"koe.db-config raw scheme        : {raw_scheme}",
        f"koe.db-config effective driver  : {effective_scheme}",
        f"koe.db-config username          : {username!r}",
        f"koe.db-config host              : {host!r}",
        f"koe.db-config port              : {port!r}",
        f"koe.db-config database          : {database!r}",
        f"koe.db-config password_present  : {bool(password)}",
        f"koe.db-config password_length   : {len(password) if password else 0}",
        f"koe.db-config PG* env present    : {pg_env_present}",
        "koe.db-config ==================================================",
    ]
    message = "\n".join(lines)
    # Use print(flush=True) as well as logging: this runs at import time, before
    # uvicorn configures logging, so print guarantees the diagnostics reach Render logs.
    print(message, flush=True)
    logger.info("Resolved database configuration:\n%s", message)


settings = get_settings()
settings.validate_persistent_database()
database_url = settings.sqlalchemy_database_url
_log_database_configuration(settings.database_url, database_url)


def _ensure_sqlite_parent_dir(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    database = make_url(url).database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(database_url)
engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
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
        "needed_quantity": "ALTER TABLE count_entries ADD COLUMN needed_quantity VARCHAR(120) NOT NULL DEFAULT 'TBD'",
        "original_phrase": "ALTER TABLE count_entries ADD COLUMN original_phrase TEXT",
        "counted_by": "ALTER TABLE count_entries ADD COLUMN counted_by VARCHAR(255)",
    }
    with engine.begin() as connection:
        for column, statement in column_sql.items():
            if column not in existing:
                connection.execute(text(statement))
    _ensure_count_entry_quantity_nullable()


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _ensure_count_entry_quantity_nullable() -> None:
    inspector = inspect(engine)
    if "count_entries" not in inspector.get_table_names():
        return

    quantity = next((column for column in inspector.get_columns("count_entries") if column["name"] == "quantity"), None)
    if not quantity or quantity.get("nullable", True):
        return

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE count_entries ALTER COLUMN quantity DROP NOT NULL"))
        return

    if engine.dialect.name != "sqlite":
        return

    from app import models  # noqa: F401

    table = Base.metadata.tables["count_entries"]
    with engine.begin() as connection:
        old_columns = [row[1] for row in connection.execute(text("PRAGMA table_info(count_entries)"))]
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text("ALTER TABLE count_entries RENAME TO count_entries_old"))
        for index in connection.execute(text("PRAGMA index_list(count_entries_old)")):
            index_name = index[1]
            if not str(index_name).startswith("sqlite_autoindex"):
                connection.execute(text(f"DROP INDEX IF EXISTS {_quote_identifier(index_name)}"))
        for index in table.indexes:
            connection.execute(text(f"DROP INDEX IF EXISTS {_quote_identifier(index.name)}"))
        table.create(bind=connection)
        copy_columns = [column.name for column in table.columns if column.name in old_columns]
        column_list = ", ".join(_quote_identifier(column) for column in copy_columns)
        connection.execute(
            text(f"INSERT INTO count_entries ({column_list}) SELECT {column_list} FROM count_entries_old")
        )
        connection.execute(text("DROP TABLE count_entries_old"))
        connection.execute(text("PRAGMA foreign_keys=ON"))
