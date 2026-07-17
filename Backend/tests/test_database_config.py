import pytest

from app.config import Settings
from app import seed as seed_module


def test_postgres_database_url_uses_psycopg_driver() -> None:
    settings = Settings(_env_file=None, database_url="postgres://user:pass@example.com:5432/koe")

    assert settings.sqlalchemy_database_url == "postgresql+psycopg://user:pass@example.com:5432/koe"


def test_postgresql_database_url_uses_psycopg_driver() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://user:pass@example.com:5432/koe")

    assert settings.sqlalchemy_database_url == "postgresql+psycopg://user:pass@example.com:5432/koe"


def test_production_sqlite_requires_explicit_persistent_disk_override() -> None:
    settings = Settings(_env_file=None, environment="production", database_url="sqlite:///./data/koe.db")

    with pytest.raises(RuntimeError, match="Unsafe production database configuration"):
        settings.validate_persistent_database()


def test_render_sqlite_requires_explicit_persistent_disk_override(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    settings = Settings(_env_file=None, environment="development", database_url="sqlite:///./data/koe.db")

    with pytest.raises(RuntimeError, match="Unsafe production database configuration"):
        settings.validate_persistent_database()


def test_production_sqlite_can_be_explicitly_allowed_for_persistent_disk() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="sqlite:////var/data/koe.db",
        allow_production_sqlite=True,
    )

    settings.validate_persistent_database()


def test_seed_reset_is_blocked_in_production(monkeypatch) -> None:
    settings = Settings(_env_file=None, environment="production")
    monkeypatch.setattr(seed_module, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="Refusing to reset seed data in production"):
        seed_module.seed(reset=True)
