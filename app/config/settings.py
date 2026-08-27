"""Central application configuration.

All configuration is sourced from environment variables (see .env.example).
Never hard-code secrets or model names here - everything must stay overridable
via the environment so deployments can change models/keys without a code change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: str = Field(default="")
    # NoDecode: pydantic-settings otherwise tries to JSON-parse a list-typed
    # env var before validators run - a comma-separated value like
    # "111,222" isn't valid JSON and raises a hard SettingsError, and even a
    # single bare number like "123456789" gets silently JSON-decoded to an
    # int instead of reaching _parse_id_list as a string. NoDecode passes
    # the raw env string straight through to the validator instead.
    allowed_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    webhook_url: str = Field(default="")
    webhook_secret: str = Field(default="")
    webhook_path: str = Field(default="/webhook")
    webapp_host: str = Field(default="0.0.0.0")
    webapp_port: int = Field(default=8080)

    # --- Gemini ---
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-3.6-flash")
    gemini_request_timeout_seconds: int = Field(default=120)
    gemini_max_retries: int = Field(default=3)
    # Explicit ceiling, not left to the SDK/model implicit default - a
    # dense/bilingual scanned page can genuinely need a large JSON response;
    # see gemini_service.py's _generate() for the real incident this backs.
    gemini_max_output_tokens: int = Field(default=65536)

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://doc_ai:doc_ai@localhost:5432/doc_ai_bot"
    )

    # --- Redis / Celery ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- File handling ---
    max_file_size_mb: int = Field(default=50)
    file_retention_hours: int = Field(default=24)
    max_pdf_pages: int = Field(default=60)
    max_batch_size: int = Field(default=10)
    storage_root: str = Field(default="storage")

    # --- Logging ---
    log_level: str = Field(default="INFO")

    # --- Health endpoint ---
    health_host: str = Field(default="0.0.0.0")
    health_port: int = Field(default=8081)

    @field_validator("allowed_telegram_ids", "admin_telegram_ids", mode="before")
    @classmethod
    def _parse_id_list(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, int):
            # pydantic-settings JSON-decodes a bare-numeric env var (e.g. a
            # single ID with no comma, "123456789") into an int before this
            # validator runs - only a comma-separated value survives as str.
            return [value]
        if isinstance(value, str):
            return [int(v.strip()) for v in value.split(",") if v.strip()]
        raise ValueError("Invalid telegram id list")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_root).resolve()

    @property
    def uploads_dir(self) -> Path:
        return self.storage_path / "uploads"

    @property
    def processed_dir(self) -> Path:
        return self.storage_path / "processed"

    @property
    def outputs_dir(self) -> Path:
        return self.storage_path / "outputs"

    def is_allowed(self, telegram_id: int) -> bool:
        # Empty allowlist means "no one is allowed" by design - fail closed.
        return telegram_id in self.allowed_telegram_ids

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_telegram_ids


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (settings.uploads_dir, settings.processed_dir, settings.outputs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
