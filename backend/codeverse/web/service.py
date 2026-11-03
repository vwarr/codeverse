"""Request logic for the Vercel functions in /api. No HTTP here: see handler.py for that.

Every route takes a `Request` and the `Deps` (settings, store, Gemini, runner) and returns a JSON-able
value or raises `ApiError`. Tests call these functions directly with fakes.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..config import Settings, get_settings
from ..execution import CodeRunner, LocalRunner, RunResult, SandboxRunner, job_for
from ..interview import prompts
from ..interview.feedback import FeedbackGenerator
from ..interview.tools import declarations
from ..interview.tracks import TRACKS, get_track
from ..problems.bank import ProblemBank, get_bank
from .store import SessionRow, Store

log = logging.getLogger(__name__)

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
MAX_CODE_CHARS = 100_000
MAX_TRANSCRIPT_TURNS = 1000
MAX_TURN_CHARS = 5000

# Takes the CreateAuthTokenConfig dict, returns the token name the browser uses as its API key.
TokenMinter = Callable[[dict[str, Any]], str]


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(slots=True)
class Request:
    query: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names
    ip: str = "?"


@dataclass(slots=True)
class Deps:
    settings: Settings
    store: Store
    mint_token: TokenMinter
    feedback: Callable[[], FeedbackGenerator]
    bank: ProblemBank = field(default_factory=get_bank)
    runner: CodeRunner | None = None  # None: running candidate code is off
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex


# ---------------------------------------------------------------------- tracks and problems
def list_tracks(_req: Request, _deps: Deps) -> list[dict[str, Any]]:
    return [t.public() for t in TRACKS.values()]


def list_problems(req: Request, deps: Deps) -> Any:
    problem_id = req.query.get("id")
    if problem_id:
        problem = deps.bank.get(problem_id)
        if problem is None:
            raise ApiError(404, "problem not found")
        return problem.public()
    track = req.query.get("track") or None
    difficulty = req.query.get("difficulty") or None
    if track is not None and track not in TRACKS:
        raise ApiError(400, f"unknown track {track!r}")
    if difficulty is not None and difficulty not in ("easy", "medium", "hard"):
        raise ApiError(400, f"unknown difficulty {difficulty!r}")
    return [p.public() for p in deps.bank.list(track=track, difficulty=difficulty)]  # type: ignore[arg-type]


# ---------------------------------------------------------------------- session token
def live_token_config(
    *, settings: Settings, system_prompt: str, tools: list[dict[str, Any]], now: dt.datetime
) -> dict[str, Any]:
    """The ephemeral-token request. Everything the model must not let the browser change is set here.

    `lock_additional_fields=[]` locks every field set in the constraints (model, system
    instruction, tools, voice, transcription, compression) and leaves the rest to the browser:
    the browser only adds `sessionResumption` with its latest handle when it reconnects.
    """
    live_config: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "context_window_compression": {"sliding_window": {}},
    }
    if tools:
        live_config["tools"] = [{"function_declarations": tools}]
    if settings.live_voice:
        live_config["speech_config"] = {
            "voice_config": {"prebuilt_voice_config": {"voice_name": settings.live_voice}}
        }
    minutes = settings.max_session_minutes + settings.session_grace_minutes
    return {
        "uses": 1,
        # Messages after this time are rejected: the hard stop for MAX_SESSION_MINUTES.
        "expire_time": now + dt.timedelta(minutes=minutes),
        # The browser must open the session within a minute. Resuming does not count as a use.
        "new_session_expire_time": now + dt.timedelta(minutes=1),
        "live_connect_constraints": {"model": settings.gemini_live_model, "config": live_config},
        "lock_additional_fields": [],
    }


def create_session(req: Request, deps: Deps) -> dict[str, Any]:
    settings, body = deps.settings, req.body
    try:
        track = get_track(str(body.get("track", "swe")))
    except LookupError as exc:
        raise ApiError(400, str(exc)) from exc

    problem_id = body.get("problemId")
    if problem_id:
        problem = deps.bank.get(str(problem_id))
        if problem is None or problem.track != track.id:
            raise ApiError(400, f"Unknown problem {problem_id!r} for track {track.id}.")
    else:
        try:
            problem = deps.bank.random(track=track.id, difficulty=body.get("difficulty") or None)  # type: ignore[arg-type]
        except LookupError as exc:
            raise ApiError(400, str(exc)) from exc

    language = str(body.get("language") or "python")
    if track.languages and language not in track.languages:
        language = track.languages[0]

    now = deps.now()
    if deps.store.active_sessions_for_ip(req.ip, now) >= settings.max_sessions_per_ip:
        raise ApiError(429, "Too many interviews from this address. Finish one or try again later.")

    config = live_token_config(
        settings=settings,
        system_prompt=track.system_prompt(problem),
        tools=declarations(track.tool_names),
        now=now,
    )
    try:
        token = deps.mint_token(config)
    except Exception as exc:  # noqa: BLE001
        log.exception("could not mint a Live API token")
        if is_rate_limited(exc):
            raise ApiError(
                503, "The interviewer is over its rate limit. Try again in a few minutes."
            ) from exc
        raise ApiError(502, f"Could not start the interviewer: {exc}") from exc

    session_id = deps.new_id()
    deps.store.create_session(
        SessionRow(
            id=session_id,
            ip=req.ip,
            track=track.id,
            problem_id=problem.id,
            language=language,
            created_at=now,
            expires_at=config["expire_time"],
            client_id=_client_id(body.get("clientId")),
        )
    )
    log.info("session %s: %s / %s", session_id, track.id, problem.id)
    return {
        "ok": True,
        "token": token,
        "apiVersion": settings.gemini_live_api_version,
        "model": settings.gemini_live_model,
        "maxSeconds": settings.max_session_minutes * 60,
        "expiresAt": config["expire_time"].isoformat(),
        "codeDebounceSeconds": settings.code_context_debounce_seconds,
        # Not secret: these are the user turns the browser sends to open and close the interview.
        "openingInstruction": prompts.OPENING_INSTRUCTION,
        "wrapUpInstruction": prompts.WRAP_UP_INSTRUCTION,
        "session": {
            "sessionId": session_id,
            "state": "connecting",
            "track": track.id,
            "surface": track.surface,
            "languages": list(track.languages),
            # Per problem: 9 swe problems have no tests (linked lists, LRU cache, ...).
            "canRun": track.can_run and deps.runner is not None and problem.has_tests,
            "problem": problem.public(),
            "language": language,
            "inputSampleRate": INPUT_SAMPLE_RATE,
            "outputSampleRate": OUTPUT_SAMPLE_RATE,
            "promptVersion": prompts.PROMPT_VERSION,
        },
    }


# ---------------------------------------------------------------------- test runs
def _session(deps: Deps, body: dict[str, Any]) -> SessionRow:
    session_id = body.get("sessionId")
    row = deps.store.get_session(str(session_id)) if session_id else None
    if row is None:
        raise ApiError(404, "No such interview.")
    return row


def _code(body: dict[str, Any]) -> str:
    code = body.get("code")
    if code is None:
        return ""
    if not isinstance(code, str):
        raise ApiError(400, "code must be a string")
    if len(code) > MAX_CODE_CHARS:
        raise ApiError(413, "The code is too long.")
    return code


async def _run(deps: Deps, job: Any) -> RunResult:
    assert deps.runner is not None
    return await deps.runner.run(job)


async def run_tests(req: Request, deps: Deps) -> dict[str, Any]:
    settings = deps.settings
    if deps.runner is None:
        raise ApiError(403, "Running code is not available for this interview.")
    row = _session(deps, req.body)
    track = get_track(row.track)
    problem = deps.bank.get(row.problem_id)
    code = _code(req.body)
    job = job_for(problem, code, time_limit=settings.code_run_timeout_seconds) if problem else None
    if not track.can_run or job is None:
        raise ApiError(400, "Running code is not available for this interview.")
    if row.ended_at is not None or row.expires_at <= deps.now():
        raise ApiError(409, "The interview is not in progress.")
    run = deps.store.claim_run(row.id, settings.max_runs_per_session)
    if run is None:
        raise ApiError(429, f"Run limit reached ({settings.max_runs_per_session} runs per interview).")
    try:
        result = await _run(deps, job)
    except Exception as exc:  # noqa: BLE001
        log.exception("session %s: test run failed", row.id)
        raise ApiError(502, "Could not run the tests. Try again.") from exc
    # `summary` is the plain-text form the interviewer model sees (context and get_last_test_run).
    return {"ok": True, "result": {"run": run, **result.public()}, "summary": result.summary(max_failures=8)}


# ---------------------------------------------------------------------- report
def _transcript(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw = body.get("transcript") or []
    if not isinstance(raw, list):
        raise ApiError(400, "transcript must be a list")
    turns: list[dict[str, Any]] = []
    for item in raw[:MAX_TRANSCRIPT_TURNS]:
        if not isinstance(item, dict) or item.get("role") not in ("candidate", "interviewer"):
            raise ApiError(400, "each transcript turn needs a role of candidate or interviewer")
        t = item.get("t", 0)
        turns.append(
            {
                "role": item["role"],
                "text": str(item.get("text") or "")[:MAX_TURN_CHARS],
                "t": float(t) if isinstance(t, int | float) else 0.0,
            }
        )
    return turns


def is_rate_limited(exc: BaseException) -> bool:
    """A 429 / quota error from Gemini (google-genai APIError or anything that says so)."""
    text = str(exc)
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in text or "429" in text.split(".")[0]


def is_transient(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    return is_rate_limited(exc) or code in (500, 502, 503, 504) or "UNAVAILABLE" in str(exc)


async def _generate_with_retry(deps: Deps, **kwargs: Any) -> Any:
    """Retry rate limits and overloads a few times; the function has minutes, not seconds."""
    delays = deps.settings.report_retry_delays
    for attempt in range(len(delays) + 1):
        try:
            return await deps.feedback().generate(**kwargs)
        except Exception as exc:  # noqa: BLE001
            if attempt == len(delays) or not is_transient(exc):
                raise
            log.warning("report generation failed (%s); retrying in %ss", exc, delays[attempt])
            await deps.sleep(delays[attempt])
    raise AssertionError("unreachable")


async def create_report(req: Request, deps: Deps) -> dict[str, Any]:
    """Save the transcript first (status "pending"), then grade and write the report.

    The transcript is never lost: if the text model fails, the record stays in Neon with status
    "failed" and the error, and a later POST for the same session tries again.
    """
    row = _session(deps, req.body)
    try:
        return await _create_report(row, req, deps)
    finally:
        # The interview is over either way, even when the request is rejected: no more test runs,
        # and the per-IP slot is free.
        deps.store.end_session(row.id, deps.now())


async def _create_report(row: SessionRow, req: Request, deps: Deps) -> dict[str, Any]:
    existing = deps.store.get_report(row.id)
    if existing is not None and existing.get("status", "complete") == "complete":
        # A retry must not bill the text model twice.
        return {"ok": True, "report": existing["report"], "finalRun": existing.get("finalRun")}

    track = get_track(row.track)
    problem = deps.bank.get(row.problem_id)
    if problem is None:
        raise ApiError(404, "The problem for this interview no longer exists.")
    transcript = _transcript(req.body)
    code = _code(req.body)
    metrics = req.body.get("metrics") if isinstance(req.body.get("metrics"), dict) else None
    if existing is not None and not transcript:  # a bare retry: use what was saved
        transcript, code = existing.get("transcript") or [], existing.get("code") or code
        metrics = metrics or existing.get("metrics")

    record: dict[str, Any] = {
        "sessionId": row.id,
        "status": "pending",
        "track": track.id,
        "problemId": problem.id,
        "promptVersion": prompts.PROMPT_VERSION,
        "createdAt": deps.now().isoformat(),
        "transcript": transcript,
        "code": code,
        "metrics": metrics,
        "endReason": req.body.get("endReason") if isinstance(req.body.get("endReason"), str) else None,
        "finalRun": None,
        "report": None,
        "error": None,
    }
    deps.store.save_report(row.id, record)

    test_summary: str | None = None
    job = job_for(problem, code, time_limit=deps.settings.code_run_timeout_seconds)
    if track.grade_final_run and deps.runner is not None and job is not None:
        # Grade the code as it was left, whether or not the candidate ran it last.
        try:
            result = await _run(deps, job)
            record["finalRun"] = result.public()
            test_summary = result.summary(max_failures=12)
        except Exception:  # noqa: BLE001
            log.exception("session %s: final test run failed", row.id)

    try:
        report = await _generate_with_retry(
            deps,
            track_id=track.id,
            problem_text=problem.prompt_text(),
            transcript=transcript,
            code=code if track.surface == "editor" else None,
            test_summary=test_summary,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("session %s: feedback generation failed", row.id)
        busy = is_rate_limited(exc)
        record.update(status="failed", error=f"{'rate limited: ' if busy else ''}{exc}"[:1000])
        deps.store.save_report(row.id, record)
        reason = "the report model is over its rate limit" if busy else "the report model failed"
        raise ApiError(
            503 if busy else 502,
            f"Could not write the feedback report ({reason}). Your transcript is saved; try again later.",
        ) from exc

    record.update(status="complete", report=report.model_dump())
    deps.store.save_report(row.id, record)
    return {"ok": True, "report": record["report"], "finalRun": record["finalRun"]}


def end_session(req: Request, deps: Deps) -> dict[str, Any]:
    """POST /api/end: the browser gave up on the interview without asking for a report.

    Called when the Live connection fails before the interview starts, and by `sendBeacon` when
    the tab closes. Ends the session so it frees its per-IP slot. Idempotent.
    """
    row = _session(deps, req.body)
    deps.store.end_session(row.id, deps.now())
    return {"ok": True}


def get_report(req: Request, deps: Deps) -> dict[str, Any]:
    session_id = req.query.get("sessionId")
    record = deps.store.get_report(session_id) if session_id else None
    if record is None:
        raise ApiError(404, "report not found")
    return record


HISTORY_LIMIT = 50


def _client_id(value: Any) -> str | None:
    """A browser's client ID (a UUID from crypto.randomUUID), normalised, or None if invalid."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        return None


def list_history(req: Request, deps: Deps) -> dict[str, Any]:
    """GET /api/history: saved reports for one browser, newest first. Header: X-Client-Id.

    There are no accounts. The browser keeps a random client ID in localStorage and sends it with
    POST /api/session. The ID works as a bearer value: only that client's reports are listed, and
    never across clients. The IP is used only for the session limit.
    """
    client_id = _client_id(req.headers.get("x-client-id"))
    if client_id is None:
        raise ApiError(400, "A valid X-Client-Id header is required.")
    reports = []
    for item in deps.store.list_reports(client_id, HISTORY_LIMIT):
        problem = deps.bank.get(str(item.get("problemId")))
        reports.append(
            {
                **item,
                "problemTitle": problem.title if problem else item.get("problemId"),
                "difficulty": problem.difficulty if problem else None,
            }
        )
    return {"ok": True, "reports": reports}


# ---------------------------------------------------------------------- production wiring
def make_runner(settings: Settings, environ: Any = os.environ) -> CodeRunner | None:
    """The code runner for these settings, or None when candidate code must not run."""
    if not settings.code_execution_enabled:
        return None
    if settings.code_runner == "sandbox":
        return SandboxRunner()
    if environ.get("VERCEL_ENV") in ("production", "preview"):
        # A deployed function holds the project's secrets; never run candidate code next to them.
        log.error("CODE_RUNNER=local is not allowed on a Vercel deployment; code execution is off")
        return None
    return LocalRunner()


@lru_cache
def default_deps() -> Deps:
    from ..interview.feedback import GeminiFeedbackGenerator
    from .store import PostgresStore

    settings = get_settings()

    def client(**kwargs: Any) -> Any:
        from google import genai  # imported lazily: the tracks/problems functions don't need it

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        return genai.Client(api_key=settings.gemini_api_key, **kwargs)

    def mint_token(config: dict[str, Any]) -> str:
        live_client = client(http_options={"api_version": settings.gemini_live_api_version})
        return str(live_client.auth_tokens.create(config=config).name)

    return Deps(
        settings=settings,
        store=PostgresStore(settings.database_url),
        runner=make_runner(settings),
        mint_token=mint_token,
        feedback=lambda: GeminiFeedbackGenerator(client(), settings.gemini_text_model),
    )
