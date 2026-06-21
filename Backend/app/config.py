from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Koe Backend"
    database_url: str = Field(default=f"sqlite:///{BASE_DIR / 'data' / 'koe.db'}")
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    enable_external_ai: bool = False
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
