"""VoiceBackend on the Gemini Live API (google-genai, async).

One backend instance = one interview. Internally it may hold several WebSocket connections over
the interview's lifetime: the Live API closes connections after roughly ten minutes (it sends a
GoAway first) and we reconnect with the session-resumption handle so the conversation continues.
Context-window compression keeps long audio sessions under the context limit.

Everything the session layer needs is exposed through the VoiceBackend protocol; nothing here is
imported by sessions.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from .base import ToolSpec, VoiceBackend, VoiceEvent

log = logging.getLogger(__name__)

AUDIO_IN_MIME = "audio/pcm;rate=16000"
SEND_TIMEOUT = 10.0
MAX_RECONNECTS = 20


def translate_message(msg: Any) -> list[VoiceEvent]:
    """Map one LiveServerMessage to VoiceEvents. Pure; safe to unit-test with stand-in objects."""
    events: list[VoiceEvent] = []
    tool_call = getattr(msg, "tool_call", None)
    if tool_call and getattr(tool_call, "function_calls", None):
        for fc in tool_call.function_calls:
            events.append(
                VoiceEvent(
                    "tool_call",
                    tool_name=getattr(fc, "name", None),
                    tool_args=dict(getattr(fc, "args", None) or {}),
                    tool_call_id=getattr(fc, "id", None),
                )
            )

    content = getattr(msg, "server_content", None)
    if content is not None:
        model_turn = getattr(content, "model_turn", None)
        if model_turn is not None:
            for part in getattr(model_turn, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None) if inline is not None else None
                if data:
                    events.append(VoiceEvent("audio", audio=bytes(data)))
        it = getattr(content, "input_transcription", None)
        if it is not None and getattr(it, "text", None):
            events.append(VoiceEvent("user_transcript", text=it.text))
        ot = getattr(content, "output_transcription", None)
        if ot is not None and getattr(ot, "text", None):
            events.append(VoiceEvent("model_transcript", text=ot.text))
        if getattr(content, "interrupted", None):
            events.append(VoiceEvent("interrupted"))
        if getattr(content, "turn_complete", None):
            events.append(VoiceEvent("turn_complete"))
    return events


class GeminiLiveBackend(VoiceBackend):
    input_sample_rate = 16000
    output_sample_rate = 24000

    def __init__(self, *, client: Any, model: str) -> None:
        self._client = client
        self._model = model
        self._queue: asyncio.Queue[VoiceEvent | None] = asyncio.Queue()
        self._session: Any = None
        self._connected = asyncio.Event()
        self._first_connect: asyncio.Future[None] | None = None
        self._runner: asyncio.Task[None] | None = None
        self._closing = False
        self._resume_handle: str | None = None
        self._go_away = False
        self._reconnects = 0
        self._system_prompt = ""
        self._tools: list[ToolSpec] = []
        self._voice: str | None = None

    # ------------------------------------------------------------------ config
    def _build_config(self) -> Any:
        from google.genai import types

        tools: list[Any] = []
        if self._tools:
            declarations = []
            for t in self._tools:
                decl: dict[str, Any] = {"name": t.name, "description": t.description}
                if t.parameters.get("properties"):
                    decl["parameters"] = t.parameters
                declarations.append(decl)
            tools.append({"function_declarations": declarations})

        speech_config = None
        if self._voice:
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                )
            )

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=self._system_prompt)]),
            speech_config=speech_config,
            tools=tools or None,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(handle=self._resume_handle),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
        )

    # ------------------------------------------------------------------ VoiceBackend
    async def start(self, *, system_prompt: str, tools: list[ToolSpec], voice: str | None = None) -> None:
        self._system_prompt = system_prompt
        self._tools = list(tools)
        self._voice = voice
        loop = asyncio.get_running_loop()
        self._first_connect = loop.create_future()
        self._runner = asyncio.create_task(self._run(), name="gemini-live")
        await self._first_connect  # raises if the first connection fails

    async def _session_or_wait(self) -> Any:
        if self._closing:
            raise RuntimeError("voice backend is closed")
        await asyncio.wait_for(self._connected.wait(), timeout=SEND_TIMEOUT)
        return self._session

    async def send_audio(self, pcm16: bytes) -> None:
        from google.genai import types

        if not self._connected.is_set():
            return  # drop audio while reconnecting rather than stalling the socket handler
        session = self._session
        await session.send_realtime_input(audio=types.Blob(data=pcm16, mime_type=AUDIO_IN_MIME))

    async def send_context(self, text: str) -> None:
        await self._send_text(text, turn_complete=False)

    async def request_turn(self, text: str) -> None:
        await self._send_text(text, turn_complete=True)

    async def _send_text(self, text: str, *, turn_complete: bool) -> None:
        from google.genai import types

        session = await self._session_or_wait()
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text=text)])], turn_complete=turn_complete
        )

    async def send_tool_result(self, call_id: str, name: str, result: dict[str, Any]) -> None:
        from google.genai import types

        session = await self._session_or_wait()
        await session.send_tool_response(
            function_responses=[types.FunctionResponse(id=call_id, name=name, response=result)]
        )

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            ev = await self._queue.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        self._closing = True
        self._connected.clear()
        if self._runner is not None:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._runner
        await self._queue.put(None)

    # ------------------------------------------------------------------ connection loop
    async def _run(self) -> None:
        try:
            while not self._closing:
                self._go_away = False
                try:
                    await self._connect_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if self._first_connect is not None and not self._first_connect.done():
                        self._first_connect.set_exception(exc)
                        return
                    log.warning("gemini live connection error: %r", exc)
                    if not self._can_reconnect():
                        await self._queue.put(VoiceEvent("error", message=f"Voice connection lost: {exc}"))
                        return
                    await asyncio.sleep(min(0.5 * 2**self._reconnects, 5.0))
                else:
                    if self._closing or not self._can_reconnect():
                        break
                    log.info("gemini live: reconnecting with resumption handle (go_away=%s)", self._go_away)
                self._reconnects += 1
        finally:
            self._connected.clear()
            await self._queue.put(VoiceEvent("closed", message="live session ended"))
            await self._queue.put(None)  # terminate events() even if close() is never called

    def _can_reconnect(self) -> bool:
        return self._resume_handle is not None and self._reconnects < MAX_RECONNECTS

    async def _connect_once(self) -> None:
        config = self._build_config()
        async with self._client.aio.live.connect(model=self._model, config=config) as session:
            self._session = session
            self._connected.set()
            if self._first_connect is not None and not self._first_connect.done():
                self._first_connect.set_result(None)
            log.info("gemini live: connected (%s)", self._model)
            try:
                async for msg in session.receive():
                    self._track_session_state(msg)
                    for ev in translate_message(msg):
                        await self._queue.put(ev)
            finally:
                self._connected.clear()
                self._session = None

    def _track_session_state(self, msg: Any) -> None:
        update = getattr(msg, "session_resumption_update", None)
        if update is not None and getattr(update, "resumable", False) and getattr(update, "new_handle", None):
            self._resume_handle = update.new_handle
        go_away = getattr(msg, "go_away", None)
        if go_away is not None:
            self._go_away = True
            log.info("gemini live: GoAway, time_left=%s", getattr(go_away, "time_left", None))
