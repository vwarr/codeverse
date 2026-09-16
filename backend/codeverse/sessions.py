"""One InterviewSession per connected client.

The session owns the conversation state machine, the transcript, the candidate's latest code and
the timing metrics. It talks to the voice provider only through the VoiceBackend protocol and to
the client only through an `emit` callable, so it can be driven entirely by a FakeVoiceBackend in
tests.

State machine
    idle -> connecting -> listening <-> thinking <-> speaking -> wrapping_up -> ended
                                     \\-> error
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .interview import prompts
from .interview.feedback import FeedbackGenerator, FeedbackReport
from .interview.tools import tools_for
from .interview.tracks import Track
from .problems.bank import Problem
from .voice.base import ToolSpec, VoiceBackend, VoiceEvent

log = logging.getLogger(__name__)

State = Literal["idle", "connecting", "listening", "thinking", "speaking", "wrapping_up", "ended", "error"]
Emit = Callable[[str, Any], Awaitable[None]]


@dataclass(slots=True)
class TranscriptTurn:
    role: Literal["candidate", "interviewer"]
    text: str
    t: float  # seconds since session start

    def public(self) -> dict[str, Any]:
        return {"role": self.role, "text": self.text, "t": round(self.t, 2)}


@dataclass(slots=True)
class TurnMetrics:
    """Latency of one model turn: from the last candidate transcript to the first audio byte."""

    candidate_done_at: float | None = None
    first_audio_at: float | None = None
    audio_bytes: int = 0

    @property
    def response_latency_ms(self) -> float | None:
        if self.candidate_done_at is None or self.first_audio_at is None:
            return None
        return round((self.first_audio_at - self.candidate_done_at) * 1000)


@dataclass
class SessionMetrics:
    turns: list[TurnMetrics] = field(default_factory=list)
    audio_in_bytes: int = 0
    audio_out_bytes: int = 0
    tool_calls: int = 0

    def summary(self) -> dict[str, Any]:
        lat = [t.response_latency_ms for t in self.turns if t.response_latency_ms is not None]
        lat.sort()
        return {
            "model_turns": len(self.turns),
            "audio_in_seconds": round(self.audio_in_bytes / (2 * 16000), 1),
            "audio_out_seconds": round(self.audio_out_bytes / (2 * 24000), 1),
            "tool_calls": self.tool_calls,
            "response_latency_ms_p50": lat[len(lat) // 2] if lat else None,
            "response_latency_ms_max": lat[-1] if lat else None,
        }


class InterviewSession:
    def __init__(
        self,
        *,
        sid: str,
        track: Track,
        problem: Problem,
        backend: VoiceBackend,
        emit: Emit,
        feedback: FeedbackGenerator | None = None,
        language: str = "python",
        voice: str | None = None,
        code_debounce: float = 1.0,
        max_minutes: int = 45,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.sid = sid
        self.track = track
        self.problem = problem
        self.backend = backend
        self.feedback_generator = feedback
        self.language = language
        self.voice = voice
        self.code_debounce = code_debounce
        self.max_seconds = max_minutes * 60
        self._clock = clock

        self.state: State = "idle"
        self.code = ""
        self.transcript: list[TranscriptTurn] = []
        self.metrics = SessionMetrics()
        self.report: FeedbackReport | None = None
        self.prompt_version = prompts.PROMPT_VERSION
        self.started_at: float | None = None
        self.wrap_up_reason: str | None = None

        self._emit = emit
        self._pump_task: asyncio.Task[None] | None = None
        self._code_task: asyncio.Task[None] | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._pending: dict[str, str] = {"candidate": "", "interviewer": ""}
        self._current_turn: TurnMetrics | None = None
        self._last_candidate_at: float | None = None
        self._wrap_up_started = False
        self._ended = asyncio.Event()
        self._tools: list[ToolSpec] = []

    # ------------------------------------------------------------------ helpers
    def _now(self) -> float:
        return self._clock() - (self.started_at or self._clock())

    async def _set_state(self, state: State, **extra: Any) -> None:
        if self.state == state and not extra:
            return
        self.state = state
        await self._emit("session_state", {"state": state, "sessionId": self.id, **extra})

    def public(self) -> dict[str, Any]:
        return {
            "sessionId": self.id,
            "state": self.state,
            "track": self.track.id,
            "problem": self.problem.public(),
            "language": self.language,
            "inputSampleRate": self.backend.input_sample_rate,
            "outputSampleRate": self.backend.output_sample_rate,
            "promptVersion": self.prompt_version,
        }

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.state != "idle":
            raise RuntimeError(f"cannot start a session in state {self.state}")
        self.started_at = self._clock()
        await self._set_state("connecting")
        self._tools = tools_for(self, self.track.tool_names)
        try:
            await self.backend.start(
                system_prompt=self.track.system_prompt(self.problem), tools=self._tools, voice=self.voice
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("session %s: backend failed to start", self.id)
            await self._fail(f"Could not start the interviewer: {exc}")
            return
        self._pump_task = asyncio.create_task(self._pump(), name=f"pump-{self.id}")
        self._timeout_task = asyncio.create_task(self._enforce_time_limit(), name=f"timeout-{self.id}")
        await self._set_state("thinking")
        await self.backend.request_turn(prompts.OPENING_INSTRUCTION)

    async def on_audio(self, pcm16: bytes) -> None:
        if self.state not in ("listening", "thinking", "speaking"):
            return
        self.metrics.audio_in_bytes += len(pcm16)
        await self.backend.send_audio(pcm16)

    async def on_code(self, code: str, language: str | None = None) -> None:
        self.code = code
        if language:
            self.language = language
        if self.state in ("ended", "error", "idle"):
            return
        if self._code_task is not None:
            self._code_task.cancel()
        self._code_task = asyncio.create_task(self._push_code_after_debounce())

    async def _push_code_after_debounce(self) -> None:
        try:
            await asyncio.sleep(self.code_debounce)
        except asyncio.CancelledError:
            return
        if self.state in ("ended", "error"):
            return
        snapshot = self.code.strip() or "(empty editor)"
        await self.backend.send_context(
            f"[Candidate's current {self.language} code — for your reference, do not respond to this]\n{snapshot}"
        )

    async def begin_wrap_up(self, *, reason: str, via_tool: bool = False) -> bool:
        """Move to wrapping_up and ask the model for its closing turn.

        Called by the Finish button, the time limit, or the request_wrap_up tool. When the model
        itself asked (via_tool), the instruction travels back in the tool result and the model
        continues its current turn, so no extra user turn is sent — otherwise it would close twice.
        Returns False if a wrap-up was already in progress.
        """
        if self._wrap_up_started or self.state in ("ended", "error"):
            return False
        self._wrap_up_started = True
        self.wrap_up_reason = reason
        if self._code_task is not None:
            self._code_task.cancel()
        await self._set_state("wrapping_up", reason=reason)
        if not via_tool:
            await self.backend.request_turn(prompts.WRAP_UP_INSTRUCTION)
        return True

    async def finish(self, *, reason: str = "candidate") -> None:
        """Candidate pressed Finish: wrap up, wait for the closing turn (bounded), then end."""
        if self.state in ("ended", "error"):
            return
        if self.state in ("idle", "connecting"):
            await self._end()
            return
        await self.begin_wrap_up(reason=reason)
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(self._ended.wait(), timeout=30)
        if not self._ended.is_set():
            await self._end()

    async def close(self) -> None:
        """Client disconnected or server shutting down. No feedback generated if not already ended."""
        for task in (self._pump_task, self._code_task, self._timeout_task):
            if task is not None:
                task.cancel()
        if self.state not in ("ended", "error"):
            self.state = "ended"
        with contextlib.suppress(Exception):
            await self.backend.close()
        self._ended.set()

    async def wait_ended(self) -> None:
        await self._ended.wait()

    # ------------------------------------------------------------------ internals
    async def _enforce_time_limit(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(self.max_seconds)
            log.info("session %s: time limit reached", self.id)
            await self.begin_wrap_up(reason="time_limit")

    async def _fail(self, message: str) -> None:
        log.error("session %s: %s", self.id, message)
        await self._emit("error", {"message": message})
        await self._set_state("error")
        self._flush_transcript()
        self._ended.set()

    async def _end(self) -> None:
        if self.state in ("ended", "error"):
            return
        self._flush_transcript()
        if self._timeout_task is not None:
            self._timeout_task.cancel()
        await self._set_state("ended", metrics=self.metrics.summary())
        await self._generate_feedback()
        await self._emit("interview_ended", {"sessionId": self.id, "metrics": self.metrics.summary()})
        with contextlib.suppress(Exception):
            await self.backend.close()
        self._ended.set()

    async def _generate_feedback(self) -> None:
        if self.feedback_generator is None:
            return
        try:
            self.report = await self.feedback_generator.generate(
                track_id=self.track.id,
                problem_text=self.problem.prompt_text(),
                transcript=[t.public() for t in self.transcript],
                code=self.code if self.track.surface == "editor" else None,
            )
            await self._emit("feedback", {"sessionId": self.id, "report": self.report.model_dump()})
        except Exception as exc:  # noqa: BLE001
            log.exception("session %s: feedback generation failed", self.id)
            await self._emit("error", {"message": f"Could not generate the feedback report: {exc}"})

    def _flush_transcript(self) -> None:
        for role in ("candidate", "interviewer"):
            self._flush_role(role)  # type: ignore[arg-type]

    def _flush_role(self, role: Literal["candidate", "interviewer"]) -> None:
        text = self._pending[role].strip()
        if text:
            turn = TranscriptTurn(role=role, text=text, t=self._now())
            self.transcript.append(turn)
        self._pending[role] = ""

    async def _append(self, role: Literal["candidate", "interviewer"], fragment: str) -> None:
        if not fragment:
            return
        self._pending[role] += fragment
        await self._emit("transcript_delta", {"role": role, "text": fragment})

    async def _commit(self, role: Literal["candidate", "interviewer"]) -> None:
        before = len(self.transcript)
        self._flush_role(role)
        if len(self.transcript) > before:
            await self._emit("transcript_turn", self.transcript[-1].public())

    async def _pump(self) -> None:
        try:
            async for ev in self.backend.events():
                await self._handle(ev)
                if self.state in ("ended", "error"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("session %s: event pump crashed", self.id)
            await self._fail(f"Voice connection failed: {exc}")
        else:
            if self.state not in ("ended", "error"):
                # Provider closed on us mid-interview.
                await self._fail("The voice connection closed unexpectedly.")

    async def _handle(self, ev: VoiceEvent) -> None:
        kind = ev.kind
        if kind == "audio" and ev.audio:
            if self._current_turn is None:
                self._current_turn = TurnMetrics(
                    candidate_done_at=self._last_candidate_at, first_audio_at=self._clock()
                )
                self.metrics.turns.append(self._current_turn)
                if self.state in ("listening", "thinking"):
                    await self._set_state("speaking")
                elif self.state == "wrapping_up":
                    await self._emit(
                        "session_state", {"state": "wrapping_up", "sessionId": self.id, "speaking": True}
                    )
            self._current_turn.audio_bytes += len(ev.audio)
            self.metrics.audio_out_bytes += len(ev.audio)
            await self._emit("audio_out", ev.audio)

        elif kind == "user_transcript":
            self._last_candidate_at = self._clock()
            await self._append("candidate", ev.text or "")
            if self.state == "listening":
                await self._set_state("thinking")

        elif kind == "model_transcript":
            await self._append("interviewer", ev.text or "")

        elif kind == "turn_complete":
            await self._commit("candidate")
            await self._commit("interviewer")
            self._current_turn = None
            if self.state == "wrapping_up":
                await self._end()
            elif self.state in ("speaking", "thinking"):
                await self._set_state("listening")

        elif kind == "interrupted":
            await self._commit("interviewer")
            self._current_turn = None
            await self._emit("interrupted", {})
            if self.state in ("speaking", "thinking"):
                await self._set_state("listening")

        elif kind == "tool_call":
            await self._run_tool(ev)

        elif kind == "error":
            await self._fail(ev.message or "voice backend error")

        elif kind == "closed":
            if self.state == "wrapping_up":
                await self._end()
            elif self.state not in ("ended", "error"):
                await self._fail(ev.message or "The voice connection closed.")

    async def _run_tool(self, ev: VoiceEvent) -> None:
        self.metrics.tool_calls += 1
        spec = next((t for t in self._tools if t.name == ev.tool_name), None)
        call_id = ev.tool_call_id or ""
        if spec is None or spec.handler is None:
            result: dict[str, Any] = {"error": f"unknown tool {ev.tool_name!r}"}
        else:
            try:
                result = await spec.handler(ev.tool_args or {})
            except Exception as exc:  # noqa: BLE001
                log.exception("session %s: tool %s failed", self.id, ev.tool_name)
                result = {"error": str(exc)}
        await self._emit("tool_call", {"name": ev.tool_name, "args": ev.tool_args, "result": result})
        await self.backend.send_tool_result(call_id, ev.tool_name or "", result)
