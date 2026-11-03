import asyncio
import unittest
from typing import Any

from codeverse.interview import prompts
from codeverse.interview.feedback import StaticFeedbackGenerator
from codeverse.interview.tracks import get_track
from codeverse.problems.bank import load_bank
from codeverse.sessions import InterviewSession
from codeverse.voice.base import VoiceEvent
from codeverse.voice.fake import FakeVoiceBackend


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    async def __call__(self, event: str, data: Any) -> None:
        self.events.append((event, data))

    def of(self, event: str) -> list[Any]:
        return [d for e, d in self.events if e == event]

    def states(self) -> list[str]:
        return [d["state"] for d in self.of("session_state")]


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def make(self, *, track_id: str = "swe", problem_id: str = "two-sum", **kw: Any):
        bank = load_bank()
        problem = bank.get(problem_id)
        assert problem is not None
        backend = FakeVoiceBackend()
        rec = Recorder()
        clock = FakeClock()
        feedback = StaticFeedbackGenerator()
        session = InterviewSession(
            sid="sid-1",
            track=get_track(track_id),
            problem=problem,
            backend=backend,
            emit=rec,
            feedback=feedback,
            clock=clock,
            code_debounce=0.01,
            **kw,
        )
        return session, backend, rec, clock, feedback

    async def test_start_opens_backend_and_requests_opening_turn(self) -> None:
        session, backend, rec, _, _ = self.make()
        await session.start()
        self.assertTrue(backend.started)
        assert backend.system_prompt is not None
        self.assertIn("Two Sum", backend.system_prompt)
        self.assertEqual([t.name for t in backend.tools], ["get_current_code", "request_wrap_up"])
        self.assertEqual(backend.turn_requests, [prompts.OPENING_INSTRUCTION])
        self.assertEqual(rec.states(), ["connecting", "thinking"])
        self.assertEqual(session.public()["problem"]["id"], "two-sum")
        await session.close()

    async def test_model_turn_streams_audio_and_transcript(self) -> None:
        session, backend, rec, clock, _ = self.make()
        await session.start()
        clock.t = 101.0
        await backend.speak("Hello and welcome.", audio_chunks=3)
        await settle()
        self.assertEqual(session.state, "listening")
        self.assertEqual(rec.states(), ["connecting", "thinking", "speaking", "listening"])
        self.assertEqual(len(rec.of("audio_out")), 3)
        self.assertEqual(
            rec.of("transcript_turn"), [{"role": "interviewer", "text": "Hello and welcome.", "t": 1.0}]
        )
        self.assertEqual([t.text for t in session.transcript], ["Hello and welcome."])
        await session.close()

    async def test_candidate_audio_forwarded_only_while_live(self) -> None:
        session, backend, _, _, _ = self.make()
        await session.on_audio(b"\x00\x01")  # idle: dropped
        await session.start()
        await backend.speak("Hi")
        await settle()
        await session.on_audio(b"\x00\x01" * 10)
        self.assertEqual(backend.audio_received, [b"\x00\x01" * 10])
        self.assertEqual(session.metrics.audio_in_bytes, 20)
        await session.close()

    async def test_code_updates_are_debounced_to_latest_snapshot(self) -> None:
        session, backend, _, _, _ = self.make()
        await session.start()
        await session.on_code("a = 1", "python")
        await session.on_code("a = 1\nb = 2", "python")
        await asyncio.sleep(0.05)
        self.assertEqual(len(backend.context_received), 1)
        self.assertIn("a = 1\nb = 2", backend.context_received[0])
        self.assertIn("python", backend.context_received[0])
        self.assertIn("do not respond", backend.context_received[0])
        await session.close()

    async def test_user_transcript_marks_thinking_and_latency_is_measured(self) -> None:
        session, backend, rec, clock, _ = self.make()
        await session.start()
        await backend.speak("Hi")
        await settle()
        clock.t = 110.0
        await backend.push(VoiceEvent("user_transcript", text="I would use a hash map"))
        await settle()
        self.assertEqual(session.state, "thinking")
        clock.t = 110.8
        await backend.speak("Good, go on.")
        await settle()
        self.assertEqual(session.state, "listening")
        self.assertEqual([t.role for t in session.transcript], ["interviewer", "candidate", "interviewer"])
        self.assertEqual(session.metrics.turns[-1].response_latency_ms, 800)
        summary = session.metrics.summary()
        self.assertEqual(summary["model_turns"], 2)
        self.assertEqual(summary["response_latency_ms_max"], 800)
        await session.close()

    async def test_tool_get_current_code_returns_editor_contents(self) -> None:
        session, backend, rec, _, _ = self.make()
        await session.start()
        await session.on_code("def two_sum(nums, target):\n    return []", "python")
        await backend.push(VoiceEvent("tool_call", tool_name="get_current_code", tool_call_id="c1"))
        await settle()
        self.assertEqual(len(backend.tool_results), 1)
        call_id, name, result = backend.tool_results[0]
        self.assertEqual((call_id, name), ("c1", "get_current_code"))
        self.assertIn("return []", result["code"])
        self.assertEqual(result["line_count"], 2)
        self.assertEqual(rec.of("tool_call")[0]["name"], "get_current_code")
        self.assertEqual(session.metrics.tool_calls, 1)
        await session.close()

    async def test_unknown_tool_reports_error_to_model(self) -> None:
        session, backend, _, _, _ = self.make()
        await session.start()
        await backend.push(VoiceEvent("tool_call", tool_name="run_tests", tool_call_id="c2"))
        await settle()
        self.assertIn("error", backend.tool_results[0][2])
        await session.close()

    async def test_interviewer_wrap_up_tool_ends_session_with_feedback(self) -> None:
        session, backend, rec, _, feedback = self.make()
        await session.start()
        await backend.speak("Hi")
        await settle()
        await backend.push(VoiceEvent("tool_call", tool_name="request_wrap_up", tool_call_id="c3"))
        await settle()
        self.assertEqual(session.state, "wrapping_up")
        self.assertEqual(session.wrap_up_reason, "interviewer")
        # The instruction rides back in the tool result; no second user turn is sent.
        self.assertEqual(backend.turn_requests, [prompts.OPENING_INSTRUCTION])
        self.assertEqual(backend.tool_results[0][2]["instruction"], prompts.WRAP_UP_INSTRUCTION)
        await backend.speak("Thanks, goodbye.")
        await settle()
        self.assertEqual(session.state, "ended")
        self.assertTrue(backend.closed)
        self.assertEqual(len(feedback.calls), 1)
        self.assertEqual(feedback.calls[0]["track_id"], "swe")
        self.assertEqual(rec.of("feedback")[0]["report"]["overall_score"], 3)
        self.assertEqual(rec.of("interview_ended")[0]["metrics"]["model_turns"], 2)
        # The closing line made it into the transcript.
        self.assertEqual(session.transcript[-1].text, "Thanks, goodbye.")

    async def test_candidate_finish_waits_for_closing_turn(self) -> None:
        session, backend, rec, _, _ = self.make()
        await session.start()
        await backend.speak("Hi")
        await settle()

        async def closing_turn() -> None:
            await asyncio.sleep(0.02)
            await backend.speak("Bye.")

        asyncio.create_task(closing_turn())
        await session.finish()
        self.assertEqual(session.state, "ended")
        self.assertEqual(session.wrap_up_reason, "candidate")
        self.assertIn("ended", rec.states())

    async def test_finish_is_idempotent_and_double_wrap_up_ignored(self) -> None:
        session, backend, _, _, _ = self.make()
        await session.start()
        await backend.speak("Hi")
        await settle()
        await session.begin_wrap_up(reason="candidate")
        await session.begin_wrap_up(reason="time_limit")
        self.assertEqual(session.wrap_up_reason, "candidate")
        self.assertEqual(backend.turn_requests.count(prompts.WRAP_UP_INSTRUCTION), 1)
        await backend.speak("Bye.")
        await settle()
        await session.finish()
        self.assertEqual(session.state, "ended")

    async def test_interruption_returns_to_listening(self) -> None:
        session, backend, rec, _, _ = self.make()
        await session.start()
        await backend.push(VoiceEvent("model_transcript", text="Let me explain at length"))
        await backend.push(VoiceEvent("audio", audio=b"\x00" * 100))
        await settle()
        self.assertEqual(session.state, "speaking")
        await backend.push(VoiceEvent("interrupted"))
        await settle()
        self.assertEqual(session.state, "listening")
        self.assertEqual(len(rec.of("interrupted")), 1)
        self.assertEqual(session.transcript[-1].text, "Let me explain at length")
        await session.close()

    async def test_backend_error_fails_session(self) -> None:
        session, backend, rec, _, _ = self.make()
        await session.start()
        await backend.push(VoiceEvent("error", message="quota exceeded"))
        await settle()
        self.assertEqual(session.state, "error")
        self.assertIn("quota exceeded", rec.of("error")[0]["message"])

    async def test_backend_closing_unexpectedly_fails_session(self) -> None:
        session, backend, rec, _, _ = self.make()
        await session.start()
        await backend.close()
        await settle()
        self.assertEqual(session.state, "error")
        self.assertTrue(rec.of("error"))

    async def test_backend_start_failure_is_reported(self) -> None:
        session, backend, rec, _, _ = self.make()

        async def boom(**_: Any) -> None:
            raise RuntimeError("no api key")

        backend.start = boom  # type: ignore[method-assign]
        await session.start()
        self.assertEqual(session.state, "error")
        self.assertIn("no api key", rec.of("error")[0]["message"])

    async def test_time_limit_triggers_wrap_up(self) -> None:
        session, backend, _, _, _ = self.make()
        session.max_seconds = 0.01
        await session.start()
        await asyncio.sleep(0.05)
        self.assertEqual(session.state, "wrapping_up")
        self.assertEqual(session.wrap_up_reason, "time_limit")
        await session.close()

    async def test_close_on_disconnect_does_not_generate_feedback(self) -> None:
        session, backend, _, _, feedback = self.make()
        await session.start()
        await session.close()
        self.assertEqual(session.state, "ended")
        self.assertEqual(feedback.calls, [])
        self.assertTrue(backend.closed)


if __name__ == "__main__":
    unittest.main()


class DebugSessionTests(unittest.IsolatedAsyncioTestCase):
    """Debug track sessions run tests through the real runner (it's fast and local)."""

    def make(self, problem_id: str = "shopping-cart-leak", **kw: Any):
        problem = load_bank().get(problem_id)
        assert problem is not None
        backend = FakeVoiceBackend()
        rec = Recorder()
        feedback = StaticFeedbackGenerator()
        session = InterviewSession(
            sid="sid-d",
            track=get_track("debug"),
            problem=problem,
            backend=backend,
            emit=rec,
            feedback=feedback,
            clock=FakeClock(),
            code_debounce=0.01,
            **kw,
        )
        return session, problem, backend, rec, feedback

    async def test_public_and_tools(self) -> None:
        session, _, backend, _, _ = self.make()
        await session.start()
        pub = session.public()
        self.assertEqual((pub["surface"], pub["languages"], pub["canRun"]), ("editor", ["python"], True))
        self.assertNotIn("bugs", pub["problem"])
        self.assertEqual(
            [t.name for t in backend.tools], ["get_current_code", "get_last_test_run", "request_wrap_up"]
        )
        assert backend.system_prompt is not None
        self.assertIn("PLANTED BUGS", backend.system_prompt)
        await session.close()

    async def test_run_tests_emits_result_and_tells_the_model(self) -> None:
        session, problem, backend, rec, _ = self.make()
        await session.start()
        await backend.speak("Hi")
        await settle()
        ack = await session.run_tests(problem.starter_code["python"])
        self.assertTrue(ack["ok"], ack)
        self.assertFalse(ack["result"]["ok"])
        self.assertEqual(ack["result"]["run"], 1)
        self.assertEqual(rec.of("run_result")[0]["total"], ack["result"]["total"])
        self.assertTrue(any("ran the test suite" in c for c in backend.context_received))

        # The interviewer's tool sees the same run.
        await backend.push(VoiceEvent("tool_call", tool_name="get_last_test_run", tool_call_id="r1"))
        await settle()
        result = backend.tool_results[-1][2]
        self.assertTrue(result["ran"])
        self.assertFalse(result["code_changed_since"])
        self.assertIn("tests passed", result["summary"])

        await session.on_code(problem.reference_solution or "")
        await backend.push(VoiceEvent("tool_call", tool_name="get_last_test_run", tool_call_id="r2"))
        await settle()
        self.assertTrue(backend.tool_results[-1][2]["code_changed_since"])
        await session.close()

    async def test_last_run_tool_before_any_run(self) -> None:
        session, _, backend, _, _ = self.make()
        await session.start()
        await backend.push(VoiceEvent("tool_call", tool_name="get_last_test_run", tool_call_id="r0"))
        await settle()
        self.assertFalse(backend.tool_results[-1][2]["ran"])
        await session.close()

    async def test_run_limit_and_not_running_states(self) -> None:
        session, problem, backend, _, _ = self.make(max_runs=1)
        ack = await session.run_tests("x = 1")
        self.assertFalse(ack["ok"])  # not started yet
        await session.start()
        await backend.speak("Hi")
        await settle()
        self.assertTrue((await session.run_tests(problem.starter_code["python"]))["ok"])
        ack = await session.run_tests(problem.starter_code["python"])
        self.assertFalse(ack["ok"])
        self.assertIn("limit", ack["error"])
        await session.close()

    async def test_execution_disabled(self) -> None:
        session, _, backend, _, _ = self.make(runner=None)
        await session.start()
        await backend.speak("Hi")
        await settle()
        self.assertFalse(session.public()["canRun"])
        self.assertFalse((await session.run_tests("x = 1"))["ok"])
        await session.close()

    async def test_wrap_up_grades_final_code_and_passes_result_to_feedback(self) -> None:
        session, problem, backend, rec, feedback = self.make()
        await session.start()
        await backend.speak("Hi")
        await settle()
        await session.on_code(problem.reference_solution or "")
        await backend.push(VoiceEvent("tool_call", tool_name="request_wrap_up", tool_call_id="w"))
        await settle()
        await backend.speak("Thanks, goodbye.")
        for _ in range(200):  # the final run is a real subprocess
            if feedback.calls:
                break
            await asyncio.sleep(0.02)
        final = rec.of("final_tests")
        self.assertEqual(len(final), 1)
        self.assertTrue(final[0]["ok"], final[0])
        self.assertEqual(feedback.calls[0]["track_id"], "debug")
        self.assertIn("tests passed", feedback.calls[0]["test_summary"])
        self.assertIn("PLANTED BUGS", feedback.calls[0]["problem_text"])

    async def test_swe_track_never_runs_code(self) -> None:
        problem = load_bank().get("two-sum")
        assert problem is not None
        session = InterviewSession(
            sid="s",
            track=get_track("swe"),
            problem=problem,
            backend=FakeVoiceBackend(),
            emit=Recorder(),
        )
        self.assertFalse(session.public()["canRun"])
        await session.close()
