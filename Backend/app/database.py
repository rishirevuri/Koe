from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()
settings.validate_persistent_database()
database_url = settings.sqlalchemy_database_url


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
