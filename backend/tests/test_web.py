"""The Vercel functions (codeverse/web): token, run-tests and report routes, with fakes for Gemini."""

from __future__ import annotations

import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from codeverse.config import Settings
from codeverse.execution import LocalRunner, RunResult, TestJob
from codeverse.execution import TestOutcome as Outcome
from codeverse.interview.feedback import StaticFeedbackGenerator
from codeverse.interview.prompts import PROMPT_VERSION
from codeverse.problems.bank import get_bank
from codeverse.web import service
from codeverse.web.handler import JsonHandler, client_ip, dispatch
from codeverse.web.service import Deps, Request
from codeverse.web.store import MemoryStore

T0 = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> dt.datetime:
        return self.now


class FakeMinter:
    def __init__(self, fail: bool = False) -> None:
        self.configs: list[dict[str, Any]] = []
        self.fail = fail

    def __call__(self, config: dict[str, Any]) -> str:
        if self.fail:
            raise RuntimeError("quota exceeded")
        self.configs.append(config)
        return f"auth_tokens/fake-{len(self.configs)}"


class FakeRunner:
    def __init__(self, result: RunResult | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result or RunResult(
            passed=1,
            total=2,
            outcomes=[
                Outcome("test_a", "passed"),
                Outcome("test_b", "failed", "AssertionError: 3 != 4"),
            ],
        )

    async def run(self, job: TestJob) -> RunResult:
        self.calls.append(job)
        return self.result


async def no_sleep(_seconds: float) -> None:
    return None


def make_deps(**settings: Any) -> tuple[Deps, MemoryStore, FakeMinter, StaticFeedbackGenerator, Clock]:
    store, minter, feedback, clock = MemoryStore(), FakeMinter(), StaticFeedbackGenerator(), Clock()
    ids = iter(f"s{i}" for i in range(1, 1000))
    config = Settings(_env_file=None, gemini_live_model="live-model-x", **settings)
    deps = Deps(
        settings=config,
        store=store,
        mint_token=minter,
        feedback=lambda: feedback,
        bank=get_bank(),
        runner=FakeRunner() if config.code_execution_enabled else None,
        now=clock,
        sleep=no_sleep,
        new_id=lambda: next(ids),
    )
    return deps, store, minter, feedback, clock


def call(route: Any, deps: Deps, *, body: dict | None = None, query: dict | None = None, ip: str = "1.2.3.4"):
    return dispatch(route, Request(query=query or {}, body=body or {}, ip=ip), deps)


def debug_problem_id() -> str:
    return get_bank().list(track="debug")[0].id


def start(deps: Deps, track: str = "debug", ip: str = "1.2.3.4", **body: Any) -> dict[str, Any]:
    status, data = call(service.create_session, deps, body={"track": track, **body}, ip=ip)
    assert status == 200, data
    return data


# ---------------------------------------------------------------------- tracks and problems
def test_tracks_and_problems() -> None:
    deps, *_ = make_deps()
    status, tracks = call(service.list_tracks, deps)
    assert status == 200 and {t["id"] for t in tracks} == {"swe", "debug"}

    status, problems = call(service.list_problems, deps, query={"track": "debug"})
    assert status == 200 and problems and all(p["track"] == "debug" for p in problems)
    assert all("test_code" not in p and "bugs" not in p for p in problems)

    status, one = call(service.list_problems, deps, query={"id": problems[0]["id"]})
    assert status == 200 and one["id"] == problems[0]["id"]
    assert call(service.list_problems, deps, query={"id": "nope"})[0] == 404
    assert call(service.list_problems, deps, query={"track": "nope"})[0] == 400


# ---------------------------------------------------------------------- session token
def test_token_locks_model_prompt_and_tools() -> None:
    deps, store, minter, _, _ = make_deps(max_session_minutes=30, session_grace_minutes=2)
    pid = debug_problem_id()
    data = start(deps, problemId=pid)

    assert data["token"] == "auth_tokens/fake-1"
    assert data["model"] == "live-model-x"
    assert data["maxSeconds"] == 30 * 60
    session = data["session"]
    assert session["track"] == "debug" and session["problem"]["id"] == pid and session["canRun"]
    assert session["promptVersion"] == PROMPT_VERSION

    (config,) = minter.configs
    assert config["uses"] == 1
    assert config["expire_time"] == T0 + dt.timedelta(minutes=32)
    assert config["new_session_expire_time"] == T0 + dt.timedelta(minutes=1)
    assert config["lock_additional_fields"] == []
    constraints = config["live_connect_constraints"]
    assert constraints["model"] == "live-model-x"
    live = constraints["config"]
    prompt = live["system_instruction"]["parts"][0]["text"]
    problem = get_bank().get(pid)
    assert problem is not None and problem.bugs
    assert all(bug in prompt for bug in problem.bugs)  # the hidden bug notes are in the token only
    names = [d["name"] for d in live["tools"][0]["function_declarations"]]
    assert names == ["get_current_code", "get_last_test_run", "request_wrap_up"]
    assert "session_resumption" not in live  # the browser adds its handle on reconnect
    # The Live model must wait for every tool result before it speaks.
    assert all(d["behavior"] == "BLOCKING" for d in live["tools"][0]["function_declarations"])
    assert data["apiVersion"] == "v1beta"

    # The prompt never goes to the browser.
    assert prompt not in json.dumps(data)
    assert store.sessions[session["sessionId"]].expires_at == config["expire_time"]


def test_token_config_is_valid_for_the_sdk_and_locks_fields() -> None:
    """Serialise the config with the real google-genai SDK (no network) and check the field mask."""
    from google import genai

    deps, _, minter, _, _ = make_deps()
    start(deps, track="swe")
    sent: dict[str, Any] = {}

    class Response:
        body = json.dumps({"name": "auth_tokens/abc"})
        headers: dict[str, str] = {}

    client = genai.Client(api_key="test-key", http_options={"api_version": "v1beta"})

    def fake_request(method: str, path: str, request_dict: dict, http_options: Any = None) -> Response:
        sent.update(method=method, path=path, body=request_dict)
        return Response()

    client._api_client.request = fake_request  # type: ignore[method-assign]
    token = client.auth_tokens.create(config=minter.configs[0])
    assert token.name == "auth_tokens/abc"
    body = sent["body"]
    assert sent["path"] == "auth_tokens" and body["uses"] == 1
    setup = body["bidiGenerateContentSetup"]
    assert setup["model"].endswith("live-model-x")
    assert "systemInstruction" in setup and "tools" in setup
    decls = setup["tools"][0]["functionDeclarations"]
    assert decls and all(d["behavior"] == "BLOCKING" for d in decls), decls
    mask = body["fieldMask"].split(",")
    for field in ("model", "tools", "generationConfig.responseModalities"):
        assert field in mask, mask
    assert any(f.startswith("systemInstruction") for f in mask), mask


def test_report_frees_the_per_ip_slot_even_when_it_fails() -> None:
    deps, store, *_ = make_deps(max_sessions_per_ip=1)
    sid = start(deps)["session"]["sessionId"]
    assert call(service.create_session, deps, body={"track": "debug"})[0] == 429
    status, _ = call(service.create_report, deps, body={"sessionId": sid, "transcript": TRANSCRIPT})
    assert status == 200 and store.sessions[sid].ended_at is not None
    # A connection lost mid-interview whose report then fails still ends the session.
    sid = start(deps)["session"]["sessionId"]
    deps.feedback = lambda: Flaky(5, RuntimeError("model down"))
    body = {"sessionId": sid, "transcript": TRANSCRIPT, "endReason": "connection_lost"}
    assert call(service.create_report, deps, body=body)[0] == 502
    assert store.sessions[sid].ended_at is not None
    start(deps)


def test_memory_store_counts_only_unended_unexpired_sessions() -> None:
    from codeverse.web.store import SessionRow

    store = MemoryStore()
    later = T0 + dt.timedelta(minutes=10)
    store.create_session(SessionRow("a", "1.1.1.1", "swe", "p", "python", T0, later))
    store.create_session(SessionRow("b", "1.1.1.1", "swe", "p", "python", T0, later))
    store.create_session(SessionRow("c", "1.1.1.1", "swe", "p", "python", T0, T0))  # expired
    store.create_session(SessionRow("d", "9.9.9.9", "swe", "p", "python", T0, later))
    assert store.active_sessions_for_ip("1.1.1.1", T0) == 2
    store.end_session("a", T0)
    assert store.active_sessions_for_ip("1.1.1.1", T0) == 1


def test_per_ip_limit_counts_active_sessions_only() -> None:
    deps, store, _, _, clock = make_deps(max_sessions_per_ip=2, max_session_minutes=10)
    first = start(deps, track="swe")
    start(deps, track="swe")
    status, data = call(service.create_session, deps, body={"track": "swe"})
    assert status == 429 and "Too many" in data["error"]
    # Another address is not affected.
    start(deps, track="swe", ip="5.6.7.8")
    # Ending a session (the report flow does) frees its slot; the active one still counts.
    store.end_session(first["session"]["sessionId"], clock())
    start(deps, track="swe")
    assert call(service.create_session, deps, body={"track": "swe"})[0] == 429
    # Expired sessions do not count.
    clock.now = T0 + dt.timedelta(minutes=30)
    start(deps, track="swe")
    start(deps, track="swe")


def test_session_rejects_bad_input_and_mint_failure() -> None:
    deps, store, _, _, _ = make_deps()
    assert call(service.create_session, deps, body={"track": "nope"})[0] == 400
    assert (
        call(service.create_session, deps, body={"track": "swe", "problemId": debug_problem_id()})[0] == 400
    )
    deps.mint_token = FakeMinter(fail=True)
    status, data = call(service.create_session, deps, body={"track": "swe"})
    assert status == 502 and "quota exceeded" in data["error"]
    assert store.sessions == {}


def test_debug_track_forces_python() -> None:
    deps, *_ = make_deps()
    assert start(deps, language="java")["session"]["language"] == "python"


# ---------------------------------------------------------------------- run tests
def test_run_tests_uses_the_hidden_suite_and_counts_runs() -> None:
    deps, store, _, _, _ = make_deps(max_runs_per_session=2, code_run_timeout_seconds=4)
    sid = start(deps)["session"]["sessionId"]
    status, data = call(service.run_tests, deps, body={"sessionId": sid, "code": "x = 1"})
    assert status == 200 and data["ok"]
    assert data["result"]["run"] == 1 and data["result"]["passed"] == 1 and data["result"]["total"] == 2
    assert "1 of 2 tests passed" in data["summary"] and "test_b failed" in data["summary"]
    (job,) = deps.runner.calls  # type: ignore[union-attr]
    problem = get_bank().get(store.sessions[sid].problem_id)
    assert problem is not None
    assert job.code == "x = 1" and job.module_name == problem.module_name
    assert job.test_code == problem.test_code and job.time_limit == 4

    assert call(service.run_tests, deps, body={"sessionId": sid, "code": ""})[0] == 200
    status, data = call(service.run_tests, deps, body={"sessionId": sid, "code": ""})
    assert status == 429 and "Run limit" in data["error"]


def test_run_tests_guards() -> None:
    deps, store, _, _, clock = make_deps()
    assert call(service.run_tests, deps, body={"sessionId": "missing"})[0] == 404
    no_tests = start(deps, track="swe", problemId="reverse-linked-list")["session"]["sessionId"]
    assert call(service.run_tests, deps, body={"sessionId": no_tests})[0] == 400
    sid = start(deps)["session"]["sessionId"]
    assert call(service.run_tests, deps, body={"sessionId": sid, "code": "x" * 200_000})[0] == 413
    clock.now = T0 + dt.timedelta(hours=2)
    assert call(service.run_tests, deps, body={"sessionId": sid})[0] == 409


def test_code_execution_disabled() -> None:
    deps, *_ = make_deps(code_execution_enabled=False)
    data = start(deps)
    assert data["session"]["canRun"] is False
    status, err = call(service.run_tests, deps, body={"sessionId": data["session"]["sessionId"]})
    assert status == 403


def test_swe_run_uses_a_suite_generated_from_the_bank() -> None:
    deps, *_ = make_deps()
    sid = start(deps, track="swe", problemId="two-sum")["session"]["sessionId"]
    assert call(service.run_tests, deps, body={"sessionId": sid, "code": "def two_sum(a, b): ..."})[0] == 200
    (job,) = deps.runner.calls  # type: ignore[union-attr]
    assert job.module_name == "solution" and "from solution import two_sum" in job.test_code


def test_run_tests_with_the_real_runner() -> None:
    deps, store, *_ = make_deps()
    deps.runner = LocalRunner()
    sid = start(deps)["session"]["sessionId"]
    problem = get_bank().get(store.sessions[sid].problem_id)
    assert problem is not None
    buggy = problem.starter_code["python"]
    status, data = call(service.run_tests, deps, body={"sessionId": sid, "code": buggy})
    assert status == 200 and data["result"]["total"] > 0 and not data["result"]["ok"]


# ---------------------------------------------------------------------- report
TRANSCRIPT = [
    {"role": "interviewer", "text": "Hi, walk me through it.", "t": 1.0},
    {"role": "candidate", "text": "I'll run the tests first.", "t": 4.5},
]


def test_report_runs_final_tests_saves_and_ends_session() -> None:
    deps, store, _, feedback, _ = make_deps()
    sid = start(deps)["session"]["sessionId"]
    body = {"sessionId": sid, "transcript": TRANSCRIPT, "code": "fixed()", "metrics": {"model_turns": 3}}
    status, data = call(service.create_report, deps, body=body)
    assert status == 200 and data["ok"]
    assert data["report"]["summary"] == feedback.report.summary
    assert data["finalRun"]["passed"] == 1

    (gen,) = feedback.calls
    assert gen["track_id"] == "debug" and gen["code"] == "fixed()"
    assert gen["transcript"] == TRANSCRIPT and "1 of 2 tests passed" in gen["test_summary"]

    record = store.reports[sid]
    assert record["metrics"] == {"model_turns": 3} and record["promptVersion"] == PROMPT_VERSION
    assert store.sessions[sid].ended_at is not None

    # A retry returns the saved report and does not call the model again.
    status, again = call(service.create_report, deps, body=body)
    assert status == 200 and again["report"] == data["report"] and len(feedback.calls) == 1

    status, got = call(service.get_report, deps, query={"sessionId": sid})
    assert status == 200 and got["report"] == data["report"] and got["transcript"] == TRANSCRIPT
    assert call(service.get_report, deps, query={"sessionId": "nope"})[0] == 404


def test_report_for_swe_track_grades_code_without_tests() -> None:
    deps, _, _, feedback, _ = make_deps()
    sid = start(deps, track="swe")["session"]["sessionId"]
    status, data = call(service.create_report, deps, body={"sessionId": sid, "transcript": [], "code": "x"})
    assert status == 200 and data["finalRun"] is None
    assert feedback.calls[0]["code"] == "x" and feedback.calls[0]["test_summary"] is None
    assert deps.runner.calls == []  # type: ignore[union-attr]


class Flaky:
    """A feedback generator that fails `fails` times with `error`, then works."""

    def __init__(self, fails: int, error: Exception) -> None:
        self.fails, self.error, self.calls = fails, error, 0
        self.ok = StaticFeedbackGenerator()

    async def generate(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls <= self.fails:
            raise self.error
        return await self.ok.generate(**kwargs)


class QuotaError(Exception):
    code = 429


def test_report_retries_a_rate_limit() -> None:
    deps, store, *_ = make_deps(report_retry_delays=[1, 1])
    flaky = Flaky(2, QuotaError("429 RESOURCE_EXHAUSTED. quota"))
    deps.feedback = lambda: flaky
    sid = start(deps, track="swe")["session"]["sessionId"]
    status, data = call(service.create_report, deps, body={"sessionId": sid, "transcript": TRANSCRIPT})
    assert status == 200 and data["ok"] and flaky.calls == 3
    assert store.reports[sid]["status"] == "complete"


def test_report_failure_keeps_the_transcript_and_can_be_retried() -> None:
    deps, store, *_ = make_deps(report_retry_delays=[1])
    flaky = Flaky(2, QuotaError("429 RESOURCE_EXHAUSTED. quota"))
    deps.feedback = lambda: flaky
    sid = start(deps, track="swe")["session"]["sessionId"]
    body = {"sessionId": sid, "transcript": TRANSCRIPT, "code": "x", "endReason": "quota"}
    status, data = call(service.create_report, deps, body=body)
    assert status == 503 and "transcript is saved" in data["error"] and "rate limit" in data["error"]
    saved = store.reports[sid]
    assert saved["status"] == "failed" and saved["transcript"] == TRANSCRIPT and saved["report"] is None
    assert saved["endReason"] == "quota" and "rate limited" in saved["error"]
    assert store.sessions[sid].ended_at is not None
    # GET shows the saved transcript and the status.
    status, got = call(service.get_report, deps, query={"sessionId": sid})
    assert status == 200 and got["status"] == "failed" and got["transcript"] == TRANSCRIPT

    # A bare retry later reuses the saved transcript and completes the report.
    status, data = call(service.create_report, deps, body={"sessionId": sid})
    assert status == 200 and data["ok"]
    assert store.reports[sid]["status"] == "complete" and store.reports[sid]["transcript"] == TRANSCRIPT
    assert flaky.ok.calls[0]["transcript"] == TRANSCRIPT


def test_report_does_not_retry_a_permanent_error() -> None:
    deps, store, *_ = make_deps()
    flaky = Flaky(5, RuntimeError("model down"))
    deps.feedback = lambda: flaky
    sid = start(deps, track="swe")["session"]["sessionId"]
    status, data = call(service.create_report, deps, body={"sessionId": sid, "transcript": TRANSCRIPT})
    assert status == 502 and flaky.calls == 1 and store.reports[sid]["status"] == "failed"


def test_token_mint_rate_limit_is_a_clear_503() -> None:
    deps, store, *_ = make_deps()

    def mint(_config: dict) -> str:
        raise QuotaError("429 RESOURCE_EXHAUSTED. You exceeded your current quota")

    deps.mint_token = mint
    status, data = call(service.create_session, deps, body={"track": "swe"})
    assert status == 503 and "rate limit" in data["error"] and store.sessions == {}


def test_make_runner_never_runs_code_locally_on_a_deployment() -> None:
    from codeverse.execution import SandboxRunner

    def settings(**kw: Any) -> Settings:
        return Settings(_env_file=None, **kw)

    assert service.make_runner(settings(code_execution_enabled=False)) is None
    assert isinstance(service.make_runner(settings()), SandboxRunner)  # the default
    local = settings(code_runner="local")
    assert isinstance(service.make_runner(local, {}), LocalRunner)
    assert isinstance(service.make_runner(local, {"VERCEL_ENV": "development"}), LocalRunner)
    assert service.make_runner(local, {"VERCEL_ENV": "production"}) is None
    assert service.make_runner(local, {"VERCEL_ENV": "preview"}) is None


def test_report_rejects_bad_transcript() -> None:
    deps, store, *_ = make_deps()
    sid = start(deps, track="swe")["session"]["sessionId"]
    bad = {"sessionId": sid, "transcript": [{"role": "system", "text": "x"}]}
    assert call(service.create_report, deps, body=bad)[0] == 400
    # A rejected report still ends the interview it names.
    assert store.sessions[sid].ended_at is not None


def test_rejected_reports_end_the_session_but_unknown_ids_end_nothing() -> None:
    deps, store, *_ = make_deps()
    too_long = start(deps)["session"]["sessionId"]
    body = {"sessionId": too_long, "code": "x" * (service.MAX_CODE_CHARS + 1)}
    assert call(service.create_report, deps, body=body)[0] == 413
    assert store.sessions[too_long].ended_at is not None

    gone = start(deps)["session"]["sessionId"]
    store.sessions[gone].problem_id = "no-such-problem"
    assert call(service.create_report, deps, body={"sessionId": gone})[0] == 404
    assert store.sessions[gone].ended_at is not None

    live = start(deps)["session"]["sessionId"]
    assert call(service.create_report, deps, body={"sessionId": "nope"})[0] == 404
    assert call(service.create_report, deps, body={})[0] == 404
    assert store.sessions[live].ended_at is None


def test_end_session_is_idempotent_and_frees_the_slot() -> None:
    deps, store, _, _, clock = make_deps(max_sessions_per_ip=1)
    sid = start(deps)["session"]["sessionId"]
    assert call(service.create_session, deps, body={"track": "debug"})[0] == 429
    assert call(service.end_session, deps, body={"sessionId": sid}) == (200, {"ok": True})
    ended_at = store.sessions[sid].ended_at
    assert ended_at == T0
    clock.now = T0 + dt.timedelta(minutes=1)
    assert call(service.end_session, deps, body={"sessionId": sid}) == (200, {"ok": True})
    assert store.sessions[sid].ended_at == ended_at  # the first end stands
    assert call(service.end_session, deps, body={"sessionId": "nope"})[0] == 404
    assert call(service.end_session, deps, body={})[0] == 404
    start(deps)
    # Runs are refused after the end; a report can still be written.
    assert call(service.run_tests, deps, body={"sessionId": sid, "code": "x"})[0] == 409
    assert call(service.create_report, deps, body={"sessionId": sid, "transcript": TRANSCRIPT})[0] == 200


def test_end_endpoint_accepts_a_beacon_body() -> None:
    """navigator.sendBeacon posts a Blob: JSON with Content-Type application/json or text/plain."""
    deps, store, *_ = make_deps()

    class Handler(JsonHandler):
        POST = staticmethod(service.end_session)

    Handler.deps = staticmethod(lambda: deps)  # type: ignore[assignment]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/api/end"
        for content_type in ("application/json", "text/plain;charset=UTF-8"):
            sid = start(deps)["session"]["sessionId"]
            body = json.dumps({"sessionId": sid}).encode()
            assert _http(url, body, {"Content-Type": content_type}) == (200, {"ok": True})
            assert store.sessions[sid].ended_at is not None
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------------- HTTP adapter
@pytest.fixture
def server():
    deps, store, minter, *_ = make_deps()

    class Handler(JsonHandler):
        GET = staticmethod(service.list_problems)
        POST = staticmethod(service.create_session)

    Handler.deps = staticmethod(lambda: deps)  # type: ignore[assignment]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", store
    httpd.shutdown()


def _http(url: str, body: Any = None, headers: dict | None = None) -> tuple[int, Any]:
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_http_handler(server) -> None:
    base, store = server
    status, data = _http(f"{base}/api/problems?track=swe")
    assert status == 200 and all(p["track"] == "swe" for p in data)

    status, data = _http(f"{base}/api/session", {"track": "swe"}, {"x-forwarded-for": "9.9.9.9, 10.0.0.1"})
    assert status == 200 and data["ok"]
    assert store.sessions[data["session"]["sessionId"]].ip == "9.9.9.9"

    assert _http(f"{base}/api/session", b"not json")[0] == 400
    assert _http(f"{base}/api/session", [1, 2])[0] == 400


# ---------------------------------------------------------------------- swe test runs
def test_swe_run_tests_uses_the_generated_suite() -> None:
    deps, *_ = make_deps()
    grant = start(deps, track="swe", problemId="two-sum")
    assert grant["session"]["canRun"] is True
    assert grant["session"]["problem"]["has_tests"] is True
    assert "tests" not in grant["session"]["problem"]
    sid = grant["session"]["sessionId"]
    status, data = call(service.run_tests, deps, body={"sessionId": sid, "code": "def two_sum(a, t): ..."})
    assert status == 200 and data["ok"]
    (job,) = deps.runner.calls  # type: ignore[union-attr]
    assert job.module_name == "solution" and "from solution import two_sum" in job.test_code
    assert "ANY_ORDER = True" in job.test_code  # two-sum is flagged in bank.json


def test_swe_problem_without_tests_cannot_run() -> None:
    deps, *_ = make_deps()
    no_tests = next(p for p in get_bank().list(track="swe") if not p.tests)
    grant = start(deps, track="swe", problemId=no_tests.id)
    assert grant["session"]["canRun"] is False
    status, _ = call(service.run_tests, deps, body={"sessionId": grant["session"]["sessionId"]})
    assert status == 400


def test_swe_report_does_not_grade_a_final_run() -> None:
    deps, store, _, feedback, _ = make_deps()
    sid = start(deps, track="swe", problemId="two-sum")["session"]["sessionId"]
    status, data = call(service.create_report, deps, body={"sessionId": sid, "transcript": TRANSCRIPT})
    assert status == 200 and data["finalRun"] is None
    assert feedback.calls[0]["test_summary"] is None


# ---------------------------------------------------------------------- history
CLIENT_A = "6f1c2c1e-3c0a-4a8e-9a55-2f0d1b7c9a01"
CLIENT_B = "0b7d4e9a-8f2c-4d61-b3a0-77e5c1f2d4b8"


def _finish(deps: Deps, clock: Clock, client: str | None, ip: str = "1.1.1.1", track: str = "debug") -> str:
    sid = start(deps, track=track, ip=ip, clientId=client)["session"]["sessionId"]
    assert call(service.create_report, deps, body={"sessionId": sid, "transcript": TRANSCRIPT})[0] == 200
    clock.now += dt.timedelta(minutes=1)
    return sid


def history(deps: Deps, client: str | None) -> tuple[int, Any]:
    headers = {"x-client-id": client} if client is not None else {}
    return dispatch(service.list_history, Request(headers=headers, ip="1.1.1.1"), deps)


def test_history_lists_only_this_clients_reports() -> None:
    deps, store, _, feedback, clock = make_deps(max_sessions_per_ip=10)
    first = _finish(deps, clock, CLIENT_A)
    second = _finish(deps, clock, CLIENT_A, track="swe")
    # Client B on the SAME IP: its report must not show for A, and A's not for B.
    other = _finish(deps, clock, CLIENT_B)
    _finish(deps, clock, None)  # an old browser with no client ID is never listed
    start(deps, ip="1.1.1.1", clientId=CLIENT_A)  # no report yet: not listed

    status, data = history(deps, CLIENT_A)
    assert status == 200 and data["ok"]
    rows = data["reports"]
    assert [r["sessionId"] for r in rows] == [second, first]  # newest first
    problem = get_bank().get(store.sessions[first].problem_id)
    assert problem is not None
    assert rows[1]["problemTitle"] == problem.title and rows[1]["difficulty"] == problem.difficulty
    assert rows[1]["overallScore"] == feedback.report.overall_score and rows[1]["track"] == "debug"
    # Summary fields only: no transcript or code in the list.
    assert set(rows[0]) == {
        "sessionId",
        "track",
        "problemId",
        "createdAt",
        "overallScore",
        "problemTitle",
        "difficulty",
    }

    assert [r["sessionId"] for r in history(deps, CLIENT_B)[1]["reports"]] == [other]
    assert history(deps, CLIENT_A.upper())[1]["reports"] == rows  # same UUID, other case
    assert history(deps, "7a1e0f3c-0000-4000-8000-000000000000")[1]["reports"] == []


def test_history_requires_a_valid_client_id() -> None:
    deps, *_ = make_deps()
    for bad in (None, "", "not-a-uuid", "x" * 100):
        status, data = history(deps, bad)
        assert status == 400 and not data["ok"], bad
    # An invalid ID at session start is not stored, so it can never be listed.
    sid = start(deps, clientId="'; DROP TABLE x; --")["session"]["sessionId"]
    assert deps.store.get_session(sid).client_id is None  # type: ignore[union-attr]


def test_history_endpoint_reads_the_client_id_header() -> None:
    deps, _, _, _, clock = make_deps(max_sessions_per_ip=10)
    sid = _finish(deps, clock, CLIENT_A)

    class Handler(JsonHandler):
        GET = staticmethod(service.list_history)

    Handler.deps = staticmethod(lambda: deps)  # type: ignore[assignment]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/api/history"
        status, data = _http(url, headers={"X-Client-Id": CLIENT_A})
        assert status == 200 and [r["sessionId"] for r in data["reports"]] == [sid]
        status, data = _http(url, headers={"X-Client-Id": CLIENT_B})
        assert status == 200 and data["reports"] == []
        assert _http(url)[0] == 400
    finally:
        httpd.shutdown()


def test_postgres_store_sql_uses_client_id() -> None:
    """No Neon in tests: check the SQL shape with a fake connection."""
    from codeverse.web.store import PostgresStore, SessionRow

    class Conn:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple]] = []

        def __enter__(self) -> Conn:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, sql: str, params: tuple = ()) -> Any:
            self.calls.append((sql, params))
            return self

        def fetchall(self) -> list[tuple]:
            return [("s1", "debug", "cart", "2026-11-03T12:00:00+00:00", 4)]

        def fetchone(self) -> tuple:
            return (1,)

    conn = Conn()
    store = PostgresStore("postgres://x")
    store._connect = lambda: conn  # type: ignore[method-assign]
    store.create_session(SessionRow("s1", "1.1.1.1", "debug", "cart", "python", T0, T0, client_id=CLIENT_A))
    sql, params = conn.calls[-1]
    assert sql.count("%s") == len(params) == 10 and params[-1] == CLIENT_A
    assert store.active_sessions_for_ip("1.1.1.1", T0) == 1
    sql, params = conn.calls[-1]
    assert "ip = %s" in sql and "ended_at IS NULL" in sql and "expires_at > %s" in sql
    assert params == ("1.1.1.1", T0)
    rows = store.list_reports(CLIENT_A, 5)
    sql, params = conn.calls[-1]
    assert "s.client_id = %s" in sql and "ip" not in sql and params == (CLIENT_A, 5)
    assert rows == [
        {
            "sessionId": "s1",
            "track": "debug",
            "problemId": "cart",
            "createdAt": "2026-11-03T12:00:00+00:00",
            "overallScore": 4,
        }
    ]


# ---- client IP (per-IP session limit) ----


def test_client_ip_prefers_the_vercel_header_over_x_forwarded_for() -> None:
    # Behind varunwarrier.com's rewrite, x-forwarded-for may hold the proxy, not the visitor.
    headers = {
        "x-vercel-forwarded-for": "203.0.113.7",
        "x-real-ip": "198.51.100.2",
        "x-forwarded-for": "198.51.100.9, 10.0.0.1",
    }
    assert client_ip(headers, "127.0.0.1") == "203.0.113.7"


def test_client_ip_falls_back_in_order() -> None:
    both = {"x-real-ip": "198.51.100.2", "x-forwarded-for": "198.51.100.9"}
    assert client_ip(both, "127.0.0.1") == "198.51.100.2"
    # Only the first x-forwarded-for entry counts; later ones are proxies.
    assert client_ip({"x-forwarded-for": " 198.51.100.9 , 10.0.0.1"}, "127.0.0.1") == "198.51.100.9"
    # Empty headers are skipped, then the socket address is used.
    assert client_ip({"x-vercel-forwarded-for": " ", "x-real-ip": ""}, "127.0.0.1") == "127.0.0.1"
