"""A scriptable VoiceBackend for tests and for running the UI without an API key.

Scripts are lists of VoiceEvents. `on_request_turn` / `on_audio_chunks` let a test
decide what the "model" does when prompted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from .base import ToolSpec, VoiceBackend, VoiceEvent


class FakeVoiceBackend(VoiceBackend):
    input_sample_rate = 16000
    output_sample_rate = 24000

    def __init__(self, *, reply_to_turn: Callable[[str], list[VoiceEvent]] | None = None) -> None:
        self.started = False
        self.closed = False
        self.system_prompt: str | None = None
        self.tools: list[ToolSpec] = []
        self.voice: str | None = None
        self.audio_received: list[bytes] = []
        self.context_received: list[str] = []
        self.turn_requests: list[str] = []
        self.tool_results: list[tuple[str, str, dict[str, Any]]] = []
        self._queue: asyncio.Queue[VoiceEvent | None] = asyncio.Queue()
        self._reply_to_turn = reply_to_turn

    # -- VoiceBackend --------------------------------------------------------
    async def start(self, *, system_prompt: str, tools: list[ToolSpec], voice: str | None = None) -> None:
        self.started = True
        self.system_prompt = system_prompt
        self.tools = list(tools)
        self.voice = voice

    async def send_audio(self, pcm16: bytes) -> None:
        self.audio_received.append(pcm16)

    async def send_context(self, text: str) -> None:
        self.context_received.append(text)

    async def request_turn(self, text: str) -> None:
        self.turn_requests.append(text)
        if self._reply_to_turn is not None:
            for ev in self._reply_to_turn(text):
                await self._queue.put(ev)

    async def send_tool_result(self, call_id: str, name: str, result: dict[str, Any]) -> None:
        self.tool_results.append((call_id, name, result))

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            ev = await self._queue.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        self.closed = True
        await self._queue.put(None)

    # -- test helpers --------------------------------------------------------
    async def push(self, *events: VoiceEvent) -> None:
        for ev in events:
            await self._queue.put(ev)

    async def speak(self, text: str, *, audio_chunks: int = 2) -> None:
        """Simulate a model turn: transcript + some audio + turn_complete."""
        await self.push(VoiceEvent("model_transcript", text=text))
        for i in range(audio_chunks):
            await self.push(VoiceEvent("audio", audio=bytes([i % 256]) * 480))
        await self.push(VoiceEvent("turn_complete"))
