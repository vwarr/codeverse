"""Drives the Socket.IO handlers with a stub server so no network is involved."""

import asyncio
import unittest
from collections.abc import Callable
from typing import Any

from codeverse.config import Settings
from codeverse.interview.feedback import StaticFeedbackGenerator
from codeverse.problems.bank import load_bank
from codeverse.sockets import register_handlers
from codeverse.voice.fake import FakeVoiceBackend


class StubSio:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.emitted: list[tuple[str, Any, str | None]] = []

    def event(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self.handlers[fn.__name__] = fn
        return fn

    def on(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers[name] = fn
            return fn

        return deco

    async def emit(self, event: str, data: Any = None, to: str | None = None, **_: Any) -> None:
        self.emitted.append((event, data, to))

    def of(self, event: str, to: str) -> list[Any]:
        return [d for e, d, t in self.emitted if e == event and t == to]


class SocketHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sio = StubSio()
        self.backends: list[FakeVoiceBackend] = []

        def backend_factory() -> FakeVoiceBackend:
            b = FakeVoiceBackend()
            self.backends.append(b)
            return b

        self.settings = Settings(gemini_api_key="x", voice_backend="fake", max_sessions_per_ip=1)
        self.registry = register_handlers(
            self.sio,  # type: ignore[arg-type]
            settings=self.settings,
            bank=load_bank(),
            backend_factory=backend_factory,
            feedback_factory=StaticFeedbackGenerator,
        )
        self.h = self.sio.handlers

    async def connect(self, sid: str, ip: str = "1.2.3.4") -> None:
        await self.h["connect"](sid, {"REMOTE_ADDR": ip})

    async def test_start_with_explicit_problem(self) -> None:
        await self.connect("s1")
        res = await self.h["start_interview"](
            "s1", {"track": "swe", "problemId": "two-sum", "language": "javascript"}
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["session"]["problem"]["id"], "two-sum")
        self.assertEqual(res["session"]["language"], "javascript")
        started = self.sio.of("interview_started", "s1")
        self.assertEqual(started[0]["session"]["track"], "swe")
        self.assertTrue(self.backends[0].started)
        await self.registry.by_sid["s1"].close()

    async def test_start_random_by_difficulty(self) -> None:
        await self.connect("s1")
        res = await self.h["start_interview"]("s1", {"track": "swe", "difficulty": "hard"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["session"]["problem"]["difficulty"], "hard")
        await self.registry.by_sid["s1"].close()

    async def test_rejects_wrong_track_problem_and_unknown_track(self) -> None:
        await self.connect("s1")
        res = await self.h["start_interview"]("s1", {"track": "ib", "problemId": "two-sum"})
        self.assertFalse(res["ok"])
        res = await self.h["start_interview"]("s1", {"track": "pm"})
        self.assertFalse(res["ok"])
        self.assertNotIn("s1", self.registry.by_sid)

    async def test_one_interview_per_connection_and_per_ip_cap(self) -> None:
        await self.connect("s1")
        await self.connect("s2")  # same IP
        ok = await self.h["start_interview"]("s1", {"track": "quant"})
        self.assertTrue(ok["ok"])
        dup = await self.h["start_interview"]("s1", {"track": "quant"})
        self.assertFalse(dup["ok"])
        capped = await self.h["start_interview"]("s2", {"track": "quant"})
        self.assertIn("Too many", capped["error"])
        await self.registry.by_sid["s1"].close()

    async def test_audio_and_code_routed_to_session(self) -> None:
        await self.connect("s1")
        await self.h["start_interview"]("s1", {"track": "swe", "problemId": "two-sum"})
        backend = self.backends[0]
        await backend.speak("Hi")
        await asyncio.sleep(0.01)
        await self.h["audio_in"]("s1", b"\x01\x02\x03\x04")
        await self.h["audio_in"]("s1", "not bytes")
        await self.h["code_update"]("s1", {"code": "x = 1", "language": "python"})
        self.assertEqual(backend.audio_received, [b"\x01\x02\x03\x04"])
        self.assertEqual(self.registry.by_sid["s1"].code, "x = 1")
        # audio the session produced was relayed to this sid only
        self.assertTrue(self.sio.of("audio_out", "s1"))
        await self.registry.by_sid["s1"].close()

    async def test_end_interview_wraps_up_and_frees_the_slot(self) -> None:
        await self.connect("s1")
        await self.h["start_interview"]("s1", {"track": "swe", "problemId": "two-sum"})
        backend = self.backends[0]
        await backend.speak("Hi")
        await asyncio.sleep(0.01)

        async def closing() -> None:
            await asyncio.sleep(0.02)
            await backend.speak("Bye")

        asyncio.create_task(closing())
        res = await self.h["end_interview"]("s1", {})
        self.assertTrue(res["ok"])
        self.assertNotIn("s1", self.registry.by_sid)
        self.assertTrue(self.sio.of("feedback", "s1"))
        self.assertTrue(self.sio.of("interview_ended", "s1"))
        # can start again on the same connection
        res = await self.h["start_interview"]("s1", {"track": "ib"})
        self.assertTrue(res["ok"])
        await self.registry.by_sid["s1"].close()

    async def test_disconnect_closes_session(self) -> None:
        await self.connect("s1")
        await self.h["start_interview"]("s1", {"track": "swe"})
        await self.h["disconnect"]("s1")
        self.assertNotIn("s1", self.registry.by_sid)
        self.assertTrue(self.backends[0].closed)
        self.assertEqual(self.registry.active_for_ip("1.2.3.4"), 0)


if __name__ == "__main__":
    unittest.main()
