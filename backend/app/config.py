"""Runtime configuration, read from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    database_url: str = Field(default="sqlite:///./data/fnol.db", alias="DATABASE_URL")
    storage_dir: Path = Field(default=Path("./data/uploads"), alias="STORAGE_DIR")

    # Security
    app_api_token: str = Field(default="", alias="APP_API_TOKEN")
    secrets_key: str = Field(default="", alias="FNOL_SECRETS_KEY")  # Fernet key for integration credentials
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    # LLM
    llm_provider: str = Field(default="anthropic", alias="LLM_PROVIDER")  # anthropic | openai | azure_openai
    llm_model: str = Field(default="claude-haiku-5-5", alias="LLM_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    azure_openai_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str = Field(default="", alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2024-10-21", alias="AZURE_OPENAI_API_VERSION")

    # OCR
    ocr_engine: str = Field(default="tesseract", alias="OCR_ENGINE")  # tesseract | azure_di
    azure_di_endpoint: str = Field(default="", alias="AZURE_DI_ENDPOINT")
    azure_di_key: str = Field(default="", alias="AZURE_DI_KEY")

    # Pipeline policy
    confidence_threshold: float = Field(default=0.85, alias="CONFIDENCE_THRESHOLD")
    auto_push: bool = Field(default=True, alias="AUTO_PUSH")
    max_agent_steps: int = Field(default=6, alias="MAX_AGENT_STEPS")

    # Email intake
    composio_api_key: str = Field(default="", alias="COMPOSIO_API_KEY")
    email_poll_seconds: int = Field(default=120, alias="EMAIL_POLL_SECONDS")

    # Worker
    worker_poll_seconds: float = Field(default=2.0, alias="WORKER_POLL_SECONDS")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite:///./"):
        Path(s.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return s
