"""Runtime configuration. Everything comes from the environment (or backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CodeRunnerName = Literal["sandbox", "local"]
ReportMode = Literal["single", "two_stage"]

# backend/.env by absolute path, so the Vercel functions (cwd repo root, e.g. under `vercel dev`)
# and the tests (cwd backend/) read the same file. Real environment variables win.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    # Model IDs drift; keep every one of them here and nowhere else.
    gemini_live_model: str = "gemini-3.8-live"
    gemini_text_model: str = "gemini-3.6-flash"
    # Comma list. The report tries gemini_text_model, then each of these in order, but only when a
    # model is rate limited or out of quota (each model has its own free-tier quota).
    gemini_text_fallback_models: str = "gemini-3.8-flash,gemini-3.5-flash-lite"
    # "single": one text-model call writes the report. "two_stage": report_extract_model first pulls
    # an evidence digest, then the report model (with its fallbacks) grades from the digest plus the
    # full transcript. See evals/compare_report_setups.py for the comparison.
    report_mode: ReportMode = "single"
    report_extract_model: str = "gemini-3.5-flash-lite"
    live_voice: str = "Kore"
    # API version for ephemeral tokens and the browser's Live connection. Google's ephemeral-token
    # docs say tokens work "only with the v1beta version of the API".
    gemini_live_api_version: str = "v1beta"

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
    # Turns Run tests (and the final grading run) on or off.
    code_execution_enabled: bool = True
    # Vercel functions: where candidate code runs. "sandbox" = a Vercel Sandbox microVM per run (no
    # secrets, no network). "local" = a child process; refused on Vercel deployments, because the
    # function holds secrets.
    code_runner: CodeRunnerName = "sandbox"
    code_run_timeout_seconds: float = 6.0
    max_runs_per_session: int = 20

    @property
    def text_models(self) -> list[str]:
        """The report models to try, in order: the main one, then the fallbacks, without repeats."""
        models = [self.gemini_text_model, *self.gemini_text_fallback_models.split(",")]
        return list(dict.fromkeys(m.strip() for m in models if m.strip()))


@lru_cache
def get_settings() -> Settings:
    return Settings()
