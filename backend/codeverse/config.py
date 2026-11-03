"""Runtime configuration. Everything comes from the environment (or backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VoiceBackendName = Literal["gemini_live", "pipeline_local", "fake"]
CodeRunnerName = Literal["sandbox", "local"]

# backend/.env by absolute path, so the legacy server (cwd backend/) and the Vercel functions
# (cwd repo root, e.g. under `vercel dev`) read the same file. Real environment variables win.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    # Model IDs drift; keep every one of them here and nowhere else.
    gemini_live_model: str = "gemini-3.8-live"
    gemini_text_model: str = "gemini-3.6-flash"
    live_voice: str = "Kore"
    # API version for ephemeral tokens and the browser's Live connection. Google's ephemeral-token
    # docs say tokens work "only with the v1beta version of the API".
    gemini_live_api_version: str = "v1beta"

    voice_backend: VoiceBackendName = "gemini_live"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    host: str = "0.0.0.0"
    port: int = 5100
    log_level: str = "INFO"

    # Guardrails for a public deployment. Live audio is billed per token.
    max_session_minutes: int = 45
    max_sessions_per_ip: int = 2
    code_context_debounce_seconds: float = 1.0
    # Extra token lifetime after MAX_SESSION_MINUTES, so the interviewer can finish its closing turn.
    session_grace_minutes: int = 3
    # Neon Postgres (Vercel functions): sessions for the per-IP limit, and saved reports.
    database_url: str = ""
    # Report: wait this long (seconds) before each retry after a 429 or 5xx from the text model.
    report_retry_delays: list[float] = Field(default_factory=lambda: [2.0, 8.0])
    # Debug track: run candidate Python in a local child process (see execution/runner.py).
    # Not a security boundary; only enable on a public URL inside a locked-down container.
    code_execution_enabled: bool = True
    # Vercel functions: where candidate code runs. "sandbox" = a Vercel Sandbox microVM per run (no
    # secrets, no network). "local" = a child process; refused on Vercel deployments, because the
    # function holds secrets.
    code_runner: CodeRunnerName = "sandbox"
    code_run_timeout_seconds: float = 6.0
    max_runs_per_session: int = 20

    # Legacy pipeline_local only.
    intro_path: str = ""
    end_path: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
