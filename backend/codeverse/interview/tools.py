"""Tools the interviewer model can call. The browser runs them; the server only declares them."""

from __future__ import annotations

from typing import Any

_DEFINITIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "get_current_code": (
        "Return the code currently in the candidate's editor. Call this before commenting on their "
        "code, and again whenever they say they are done or ask you to look.",
        {"type": "object", "properties": {}},
    ),
    "get_last_test_run": (
        "Return the result of the most recent time the candidate pressed Run tests: how many tests "
        "passed, failing test names and messages, printed output, and whether the code has changed "
        "since. Call this before discussing test results.",
        {"type": "object", "properties": {}},
    ),
    "request_wrap_up": (
        "Signal that the interview has covered everything and should end. Call exactly once, "
        "when the candidate is finished or time is up.",
        {"type": "object", "properties": {}},
    ),
}


def declarations(names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Function declarations for the Live API, without handlers (the browser runs the tools)."""
    out: list[dict[str, Any]] = []
    for name in names:
        description, params = _DEFINITIONS[name]
        # BLOCKING: the Live model waits for the result. Some Live models default to NON_BLOCKING,
        # which lets the model talk about code or test results it has not seen yet.
        decl: dict[str, Any] = {"name": name, "description": description, "behavior": "BLOCKING"}
        if params.get("properties"):
            decl["parameters"] = params
        out.append(decl)
    return out
