"""Legacy voice path: server microphone -> RealtimeSTT -> text model -> Cloud TTS -> server speakers.

Kept behind VOICE_BACKEND=pipeline_local so the app still runs on a single laptop without the
Live API. It implements the same VoiceBackend protocol as GeminiLiveBackend, but ignores
`send_audio` (it listens on the server's own mic) and emits no `audio` events (it plays audio
itself). Requires the `legacy-audio` optional dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

from ..config import Settings
from .base import ToolSpec, VoiceBackend, VoiceEvent

log = logging.getLogger(__name__)


class PipelineLocalBackend(VoiceBackend):
    input_sample_rate = 16000
    output_sample_rate = 24000

    def __init__(self, *, client: Any, model: str, settings: Settings) -> None:
        self._client = client
        self._model = model
        self._settings = settings
        self._queue: asyncio.Queue[VoiceEvent | None] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._chat: Any = None
        self._recorder: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending_context: list[str] = []
        self._turn_requests: asyncio.Queue[str] = asyncio.Queue()
        self._lock = threading.Lock()

    def _post(self, ev: VoiceEvent | None) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._queue.put_nowait, ev)

    async def start(self, *, system_prompt: str, tools: list[ToolSpec], voice: str | None = None) -> None:
        from google.genai import types

        self._loop = asyncio.get_running_loop()
        # Tools are not wired through the text chat in this legacy path; the model is told instead.
        tool_note = ""
        if tools:
            names = ", ".join(t.name for t in tools)
            tool_note = f"\n\n(Tools {names} are unavailable in this mode; the candidate's code is included with each message.)"
        self._chat = self._client.chats.create(
            model=self._model,
            config=types.GenerateContentConfig(system_instruction=system_prompt + tool_note),
        )
        self._thread = threading.Thread(target=self._run, name="pipeline-local", daemon=True)
        self._thread.start()

    async def send_audio(self, pcm16: bytes) -> None:  # server mic is used instead
        return None

    async def send_context(self, text: str) -> None:
        with self._lock:
            self._pending_context = [text]  # keep only the latest snapshot

    async def request_turn(self, text: str) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._turn_requests.put_nowait, text)

    async def send_tool_result(self, call_id: str, name: str, result: dict[str, Any]) -> None:
        return None

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            ev = await self._queue.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        self._stop.set()
        if self._recorder is not None:
            try:
                self._recorder.abort()
            except Exception:  # noqa: BLE001
                pass
        self._post(None)

    # ---------------------------------------------------------------- worker thread
    def _speak(self, text: str) -> None:
        from .legacy_tts import text_to_speech

        self._post(VoiceEvent("model_transcript", text=text))
        try:
            text_to_speech(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("TTS failed: %s", exc)
        self._post(VoiceEvent("turn_complete"))

    def _model_reply(self, message: str) -> str:
        with self._lock:
            context = "\n\n".join(self._pending_context)
            self._pending_context = []
        if context:
            message = f"{context}\n\n{message}"
        response = self._chat.send_message(message)
        return (response.text or "").strip()

    def _drain_turn_request(self) -> str | None:
        try:
            return self._turn_requests.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _run(self) -> None:
        try:
            from RealtimeSTT import AudioToTextRecorder

            self._recorder = AudioToTextRecorder()
            while not self._stop.is_set():
                pending = self._drain_turn_request()
                if pending is not None:
                    self._speak(self._model_reply(pending))
                    continue
                speech = self._recorder.text()
                if self._stop.is_set():
                    break
                if not speech:
                    continue
                self._post(VoiceEvent("user_transcript", text=speech))
                self._speak(self._model_reply(speech))
        except Exception as exc:  # noqa: BLE001
            log.exception("pipeline_local worker failed")
            self._post(VoiceEvent("error", message=str(exc)))
        finally:
            self._post(VoiceEvent("closed", message="pipeline stopped"))
