"""Interview tracks as data: what surface the UI shows, which tools the model has, how the prompt is built."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..problems.bank import Problem
from . import prompts

Surface = Literal["editor", "conversation"]


@dataclass(frozen=True)
class Track:
    id: str
    name: str
    description: str
    surface: Surface
    tool_names: tuple[str, ...] = field(default_factory=tuple)
    default_difficulty: str = "easy"
    # Editor languages offered. Both tracks are Python only.
    languages: tuple[str, ...] = ("python",)
    # The candidate can run the problem's hidden tests from the editor (when the problem has tests).
    can_run: bool = False
    # The grader runs the tests again on the final code and puts the result in the report.
    grade_final_run: bool = False

    def system_prompt(self, problem: Problem, *, extra_rules: str = "") -> str:
        return prompts.build_system_prompt(self.id, problem.prompt_text(), extra_rules=extra_rules)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "surface": self.surface,
            "defaultDifficulty": self.default_difficulty,
            "languages": list(self.languages),
            "canRun": self.can_run,
        }


TRACKS: dict[str, Track] = {
    "swe": Track(
        id="swe",
        name="Software engineering",
        description="A coding interview on one algorithmic problem, with a live editor.",
        surface="editor",
        tool_names=("get_current_code", "request_wrap_up"),
        can_run=True,
    ),
    "debug": Track(
        id="debug",
        name="Debugging",
        description="A bug report and a broken Python module. Reproduce, find the root cause, fix it.",
        surface="editor",
        tool_names=("get_current_code", "get_last_test_run", "request_wrap_up"),
        can_run=True,
        grade_final_run=True,
    ),
}


def get_track(track_id: str) -> Track:
    try:
        return TRACKS[track_id]
    except KeyError as exc:
        raise LookupError(f"unknown track {track_id!r}") from exc
