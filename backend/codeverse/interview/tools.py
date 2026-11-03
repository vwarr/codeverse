"""Tools the interviewer model can call. Handlers are bound to a session at start time."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ..voice.base import ToolSpec
from . import prompts

if TYPE_CHECKING:
    from ..sessions import InterviewSession

Handler = Callable[["InterviewSession", dict[str, Any]], Awaitable[dict[str, Any]]]


async def get_current_code(session: InterviewSession, _args: dict[str, Any]) -> dict[str, Any]:
    code = session.code.strip()
    return {
        "language": session.language,
        "code": code if code else "(the candidate has not written any code yet)",
        "line_count": code.count("\n") + 1 if code else 0,
    }


async def get_last_test_run(session: InterviewSession, _args: dict[str, Any]) -> dict[str, Any]:
    run = session.last_run
    if run is None:
        return {"ran": False, "note": "The candidate has not run the tests yet."}
    return {
        "ran": True,
        "runs_so_far": session.run_count,
        "seconds_ago": round(session.seconds_since_last_run() or 0),
        "code_changed_since": session.code != session.last_run_code,
        "summary": run.summary(max_failures=8),
    }


async def request_wrap_up(session: InterviewSession, _args: dict[str, Any]) -> dict[str, Any]:
    started = await session.begin_wrap_up(reason="interviewer", via_tool=True)
    if not started:
        return {"ok": False, "note": "The interview is already wrapping up; finish your closing remarks."}
    return {"ok": True, "instruction": prompts.WRAP_UP_INSTRUCTION}


_DEFINITIONS: dict[str, tuple[str, dict[str, Any], Handler]] = {
    "get_current_code": (
        "Return the code currently in the candidate's editor. Call this before commenting on their "
        "code, and again whenever they say they are done or ask you to look.",
        {"type": "object", "properties": {}},
        get_current_code,
    ),
    "get_last_test_run": (
        "Return the result of the most recent time the candidate pressed Run tests: how many tests "
        "passed, failing test names and messages, printed output, and whether the code has changed "
        "since. Call this before discussing test results.",
        {"type": "object", "properties": {}},
        get_last_test_run,
    ),
    "request_wrap_up": (
        "Signal that the interview has covered everything and should end. Call exactly once, "
        "when the candidate is finished or time is up.",
        {"type": "object", "properties": {}},
        request_wrap_up,
    ),
}


def declarations(names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Function declarations for the Live API, without handlers (the browser runs the tools)."""
    out: list[dict[str, Any]] = []
    for name in names:
        description, params, _handler = _DEFINITIONS[name]
        # BLOCKING: the Live model waits for the result. Some Live models default to NON_BLOCKING,
        # which lets the model talk about code or test results it has not seen yet.
        decl: dict[str, Any] = {"name": name, "description": description, "behavior": "BLOCKING"}
        if params.get("properties"):
            decl["parameters"] = params
        out.append(decl)
    return out


def tools_for(session: InterviewSession, names: tuple[str, ...]) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for name in names:
        description, params, handler = _DEFINITIONS[name]

        async def bound(args: dict[str, Any], _h: Handler = handler) -> dict[str, Any]:
            return await _h(session, args)

        specs.append(ToolSpec(name=name, description=description, parameters=params, handler=bound))
    return specs
