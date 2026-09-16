"""Runtime configuration. Everything comes from the environment (or backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VoiceBackendName = Literal["gemini_live", "pipeline_local", "fake"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    # Model IDs drift; keep every one of them here and nowhere else.
    gemini_live_model: str = "gemini-3.8-live"
    gemini_text_model: str = "gemini-3.5-flash"
    live_voice: str = "Kore"

    voice_backend: VoiceBackendName = "gemini_live"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    host: str = "0.0.0.0"
    port: int = 5100
    log_level: str = "INFO"

    # Guardrails for a public deployment. Live audio is billed per token.
    max_session_minutes: int = 45
    max_sessions_per_ip: int = 2
    code_context_debounce_seconds: float = 1.0

    # Legacy pipeline_local only.
    intro_path: str = ""
    finance_path: str = ""
    end_path: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
