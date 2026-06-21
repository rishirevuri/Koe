from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8")

    app_name: str = "Koe Backend"
    database_url: str = Field(default=f"sqlite:///{BASE_DIR / 'data' / 'koe.db'}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
