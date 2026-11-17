from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://recsys:recsys@localhost:5432/recsys"
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"
    embed_model: str = "bge-m3"
    jwt_secret: str = "change-me"
    session_cookie_secure: bool = False
    admin_token: str = "change-me"
    artifacts_dir: Path = Path("artifacts")
    data_dir: Path = Path("data")


@lru_cache
def get_settings() -> Settings:
    return Settings()
