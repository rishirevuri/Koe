from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Koe Backend"
    environment: str = "development"
    database_url: str = Field(default="sqlite:///./data/koe.db")
    allow_production_sqlite: bool = False
    enable_external_ai: bool = False
    debug_parse: bool = False

    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None

    elevenlabs_api_key: str | None = None
    gemini_api_key: str | None = None
    google_api_key: str | None = None
    speech_provider: str = "elevenlabs"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    text_ai_provider: str = "claude"

    google_sheets_client_id: str | None = None
    google_sheets_client_secret: str | None = None
    google_sheets_redirect_uri: str = "http://localhost:8000/integrations/google/callback"

    payments_enabled: bool = False
    payments_provider: str = "none"

    @property
    def sqlalchemy_database_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url.removeprefix("postgres://")
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql://")
        return url

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"prod", "production"}

    @property
    def is_render_runtime(self) -> bool:
        return any(os.getenv(name) for name in ("RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL"))

    @property
    def is_sqlite_database(self) -> bool:
        return self.sqlalchemy_database_url.startswith("sqlite")

    def validate_persistent_database(self) -> None:
        if not (self.is_production or self.is_render_runtime) or not self.is_sqlite_database or self.allow_production_sqlite:
            return
        raise RuntimeError(
            "Unsafe production database configuration: DATABASE_URL is SQLite. "
            "Render web service filesystems are ephemeral unless a persistent disk is mounted, "
            "so saved counts can disappear after restart/redeploy. Use a persistent Postgres/Supabase "
            "DATABASE_URL, or set ALLOW_PRODUCTION_SQLITE=true only when the SQLite file is on a "
            "Render persistent disk."
        )

    @staticmethod
    def _has_real_value(value: str | None) -> bool:
        return bool(value and value.strip() and not value.strip().startswith("your_"))

    @property
    def is_supabase_configured(self) -> bool:
        return self._has_real_value(self.supabase_url) and (
            self._has_real_value(self.supabase_anon_key) or self._has_real_value(self.supabase_service_role_key)
        )

    @property
    def is_gemini_configured(self) -> bool:
        return self._has_real_value(self.gemini_api_key)

    @property
    def is_elevenlabs_configured(self) -> bool:
        return self._has_real_value(self.elevenlabs_api_key)

    @property
    def is_claude_configured(self) -> bool:
        return self._has_real_value(self.anthropic_api_key)

    @property
    def is_google_sheets_configured(self) -> bool:
        return (
            self._has_real_value(self.google_sheets_client_id)
            and self._has_real_value(self.google_sheets_client_secret)
            and self._has_real_value(self.google_sheets_redirect_uri)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
