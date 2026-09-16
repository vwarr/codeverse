"""Socket.IO event handlers. Thin: validate, look things up, delegate to InterviewSession.

Client -> server
    start_interview {track, problemId?, difficulty?, language?}
    audio_in        <bytes>   PCM16 mono at session.inputSampleRate
    code_update     {code, language?}
    end_interview   {}
Server -> client
    interview_started {session}          session_state {state, ...}
    audio_out <bytes>                    interrupted {}
    transcript_delta {role, text}        transcript_turn {role, text, t}
    tool_call {name, args, result}       feedback {sessionId, report}
    interview_ended {sessionId, metrics} error {message}
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from typing import Any

import socketio

from .config import Settings
from .interview.feedback import FeedbackGenerator
from .interview.tracks import get_track
from .problems.bank import ProblemBank
from .sessions import InterviewSession
from .voice.base import VoiceBackend

log = logging.getLogger(__name__)

BackendFactory = Callable[[], VoiceBackend]
FeedbackFactory = Callable[[], FeedbackGenerator | None]


class SessionRegistry:
    def __init__(self, *, max_per_ip: int) -> None:
        self.by_sid: dict[str, InterviewSession] = {}
        self.ip_by_sid: dict[str, str] = {}
        self.max_per_ip = max_per_ip

    def active_for_ip(self, ip: str) -> int:
        counts = Counter(self.ip_by_sid[sid] for sid in self.by_sid if sid in self.ip_by_sid)
        return counts.get(ip, 0)


def _client_ip(environ: dict[str, Any]) -> str:
    forwarded = environ.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return environ.get("REMOTE_ADDR") or environ.get("asgi.scope", {}).get("client", ["?"])[0]


def register_handlers(
    sio: socketio.AsyncServer,
    *,
    settings: Settings,
    bank: ProblemBank,
    backend_factory: BackendFactory,
    feedback_factory: FeedbackFactory,
) -> SessionRegistry:
    registry = SessionRegistry(max_per_ip=settings.max_sessions_per_ip)

    def emitter(sid: str):
        async def emit(event: str, data: Any) -> None:
            await sio.emit(event, data, to=sid)

        return emit

    @sio.event
    async def connect(sid: str, environ: dict[str, Any], _auth: Any = None) -> None:
        registry.ip_by_sid[sid] = _client_ip(environ)
        log.info("connect %s from %s", sid, registry.ip_by_sid[sid])

    @sio.event
    async def disconnect(sid: str, *_: Any) -> None:
        session = registry.by_sid.pop(sid, None)
        registry.ip_by_sid.pop(sid, None)
        if session is not None:
            log.info("disconnect %s: closing session %s in state %s", sid, session.id, session.state)
            await session.close()

    @sio.on("start_interview")
    async def start_interview(sid: str, data: Any = None) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        if sid in registry.by_sid:
            return {"ok": False, "error": "This connection already has an interview."}
        ip = registry.ip_by_sid.get(sid, "?")
        if registry.active_for_ip(ip) >= registry.max_per_ip:
            return {"ok": False, "error": "Too many concurrent interviews from this address."}
        try:
            track = get_track(str(data.get("track", "swe")))
        except LookupError as exc:
            return {"ok": False, "error": str(exc)}

        problem_id = data.get("problemId")
        difficulty = data.get("difficulty") or None
        if problem_id:
            problem = bank.get(str(problem_id))
            if problem is None or problem.track != track.id:
                return {"ok": False, "error": f"Unknown problem {problem_id!r} for track {track.id}."}
        else:
            try:
                problem = bank.random(track=track.id, difficulty=difficulty)  # type: ignore[arg-type]
            except LookupError as exc:
                return {"ok": False, "error": str(exc)}

        session = InterviewSession(
            sid=sid,
            track=track,
            problem=problem,
            backend=backend_factory(),
            emit=emitter(sid),
            feedback=feedback_factory(),
            language=str(data.get("language") or "python"),
            voice=settings.live_voice,
            code_debounce=settings.code_context_debounce_seconds,
            max_minutes=settings.max_session_minutes,
        )
        registry.by_sid[sid] = session
        log.info("session %s: %s / %s for %s", session.id, track.id, problem.id, sid)
        await sio.emit("interview_started", {"session": session.public()}, to=sid)
        await session.start()
        return {"ok": True, "session": session.public()}

    @sio.on("audio_in")
    async def audio_in(sid: str, data: Any) -> None:
        session = registry.by_sid.get(sid)
        if session is None or not isinstance(data, bytes | bytearray):
            return
        await session.on_audio(bytes(data))

    @sio.on("code_update")
    async def code_update(sid: str, data: Any = None) -> None:
        session = registry.by_sid.get(sid)
        if session is None or not isinstance(data, dict):
            return
        await session.on_code(str(data.get("code") or ""), data.get("language"))

    @sio.on("end_interview")
    async def end_interview(sid: str, _data: Any = None) -> dict[str, Any]:
        session = registry.by_sid.get(sid)
        if session is None:
            return {"ok": False, "error": "No interview in progress."}
        await session.finish(reason="candidate")
        registry.by_sid.pop(sid, None)
        return {"ok": True, "sessionId": session.id}

    return registry
