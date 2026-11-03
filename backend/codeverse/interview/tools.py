"""Tools the interviewer model can call. The browser runs them; the server only declares them."""

from __future__ import annotations

from typing import Any

_DEFINITIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "get_current_code": (
        "Return the code currently in the candidate's editor. Call this before you comment on their "
        "code, when they say they are done, and when they ask you to look. Do not describe code you "
        "have not just fetched.",
        {"type": "object", "properties": {}},
    ),
    "get_last_test_run": (
        "Return the result of the most recent time the candidate pressed Run tests: how many tests "
        "passed, failing test names and messages, printed output, and whether the code has changed "
        "since. Call this after the candidate runs the tests and before you say anything about the "
        "result. Never say tests pass or fail without calling it first.",
        {"type": "object", "properties": {}},
    ),
    "request_wrap_up": (
        "End the interview. Call it once: when the interview phases are covered, when the candidate "
        "says they are finished, when they want to stop, or on the third off-task turn. The result "
        "contains the closing instruction to follow.",
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
