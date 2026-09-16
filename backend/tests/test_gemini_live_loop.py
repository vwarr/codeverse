"""Drives GeminiLiveBackend's connection loop with a fake google-genai client (no SDK needed)."""

import asyncio
import contextlib
import unittest
from types import SimpleNamespace as NS
from typing import Any

from codeverse.voice.gemini_live import GeminiLiveBackend

try:  # the send paths build SDK types; stub them when google-genai isn't installed
    import google.genai.types  # noqa: F401
except ImportError:  # pragma: no cover - depends on the environment
    import sys
    import types as _types

    _stub = _types.ModuleType("google.genai.types")
    for _name in ("Blob", "Content", "Part", "FunctionResponse"):
        setattr(_stub, _name, lambda **kw: kw)
    _genai = _types.ModuleType("google.genai")
    _genai.types = _stub  # type: ignore[attr-defined]
    _google = sys.modules.get("google") or _types.ModuleType("google")
    _google.genai = _genai  # type: ignore[attr-defined]
    sys.modules.setdefault("google", _google)
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = _stub


def content(**kw: Any) -> NS:
    base = {
        "model_turn": None,
        "input_transcription": None,
        "output_transcription": None,
        "interrupted": None,
        "turn_complete": None,
    }
    base.update(kw)
    return NS(**base)


def message(**kw: Any) -> NS:
    base = {"tool_call": None, "server_content": None, "session_resumption_update": None, "go_away": None}
    base.update(kw)
    return NS(**base)


class FakeSession:
    def __init__(self, script: list[Any], *, hang_after: bool) -> None:
        self.script = script
        self.hang_after = hang_after
        self.sent: list[tuple[str, Any]] = []
        self.release = asyncio.Event()

    async def receive(self):
        for m in self.script:
            yield m
        if self.hang_after:
            await self.release.wait()

    async def send_realtime_input(self, **kw: Any) -> None:
        self.sent.append(("audio", kw))

    async def send_client_content(self, **kw: Any) -> None:
        self.sent.append(("text", kw))

    async def send_tool_response(self, **kw: Any) -> None:
        self.sent.append(("tool", kw))


class FakeLive:
    def __init__(self, sessions: list[FakeSession]) -> None:
        self.sessions = sessions
        self.connect_configs: list[Any] = []

    @contextlib.asynccontextmanager
    async def connect(self, *, model: str, config: Any):
        self.connect_configs.append(config)
        session = self.sessions.pop(0)
        try:
            yield session
        finally:
            session.release.set()


class LiveLoopTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, sessions: list[FakeSession]) -> tuple[GeminiLiveBackend, FakeLive]:
        live = FakeLive(sessions)
        client = NS(aio=NS(live=live))
        backend = GeminiLiveBackend(client=client, model="fake-live")
        # The real config needs the SDK; capture the resumption handle instead.
        backend._build_config = lambda: {"handle": backend._resume_handle}  # type: ignore[method-assign]
        return backend, live

    async def test_reconnects_with_resumption_handle_and_keeps_streaming(self) -> None:
        first = FakeSession(
            [
                message(session_resumption_update=NS(resumable=True, new_handle="h1")),
                message(server_content=content(model_turn=NS(parts=[NS(inline_data=NS(data=b"aa"))]))),
                message(go_away=NS(time_left="5s")),
            ],
            hang_after=False,  # server closes after GoAway
        )
        second = FakeSession([message(server_content=content(turn_complete=True))], hang_after=True)
        backend, live = await self.make([first, second])

        await backend.start(system_prompt="sys", tools=[], voice=None)
        events = []
        async for ev in backend.events():
            events.append(ev.kind)
            if ev.kind == "turn_complete":
                break
        self.assertEqual(events, ["audio", "turn_complete"])
        self.assertEqual(len(live.connect_configs), 2)
        self.assertEqual(live.connect_configs[0]["handle"], None)
        self.assertEqual(live.connect_configs[1]["handle"], "h1")

        await backend.send_audio(b"\x01\x02")
        await backend.request_turn("wrap up")
        await backend.send_tool_result("c1", "t", {"ok": True})
        self.assertEqual([k for k, _ in second.sent], ["audio", "text", "tool"])

        await backend.close()
        # After close the stream terminates.
        tail = [ev.kind async for ev in backend.events()]
        self.assertNotIn("audio", tail)

    async def test_no_handle_means_close_is_reported(self) -> None:
        only = FakeSession([message(server_content=content(turn_complete=True))], hang_after=False)
        backend, _ = await self.make([only])
        await backend.start(system_prompt="sys", tools=[], voice=None)
        kinds = [ev.kind async for ev in backend.events()]
        # turn_complete, then the server hung up with no resumption handle: "closed", then the stream ends.
        self.assertEqual(kinds[:2], ["turn_complete", "closed"])

    async def test_first_connection_failure_raises_from_start(self) -> None:
        class Boom:
            @contextlib.asynccontextmanager
            async def connect(self, **_: Any):
                raise RuntimeError("401 unauthorized")
                yield  # pragma: no cover

        client = NS(aio=NS(live=Boom()))
        backend = GeminiLiveBackend(client=client, model="fake-live")
        backend._build_config = lambda: {}  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            await backend.start(system_prompt="sys", tools=[], voice=None)

    async def test_send_while_disconnected_drops_audio_but_waits_for_text(self) -> None:
        first = FakeSession(
            [message(session_resumption_update=NS(resumable=True, new_handle="h"))], hang_after=True
        )
        backend, live = await self.make([first, FakeSession([], hang_after=True)])
        await backend.start(system_prompt="sys", tools=[], voice=None)
        backend._connected.clear()  # simulate mid-reconnect
        await backend.send_audio(b"x")  # must not raise or block
        self.assertEqual(first.sent, [])
        backend._connected.set()
        await backend.send_context("code")
        self.assertEqual(first.sent[0][0], "text")
        self.assertFalse(first.sent[0][1]["turn_complete"])
        await backend.close()


if __name__ == "__main__":
    unittest.main()
