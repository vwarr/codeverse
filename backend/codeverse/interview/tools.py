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
    "request_wrap_up": (
        "Signal that the interview has covered everything and should end. Call exactly once, "
        "when the candidate is finished or time is up.",
        {"type": "object", "properties": {}},
        request_wrap_up,
    ),
}


def tools_for(session: InterviewSession, names: tuple[str, ...]) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for name in names:
        description, params, handler = _DEFINITIONS[name]

        async def bound(args: dict[str, Any], _h: Handler = handler) -> dict[str, Any]:
            return await _h(session, args)

        specs.append(ToolSpec(name=name, description=description, parameters=params, handler=bound))
    return specs
