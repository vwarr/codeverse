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

    def system_prompt(self, problem: Problem, *, extra_rules: str = "") -> str:
        return prompts.build_system_prompt(self.id, problem.prompt_text(), extra_rules=extra_rules)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "surface": self.surface,
            "defaultDifficulty": self.default_difficulty,
        }


TRACKS: dict[str, Track] = {
    "swe": Track(
        id="swe",
        name="Software engineering",
        description="A coding interview on one algorithmic problem, with a live editor.",
        surface="editor",
        tool_names=("get_current_code", "request_wrap_up"),
    ),
    "ib": Track(
        id="ib",
        name="Investment banking",
        description="A conversational technical interview on valuation, accounting and deals.",
        surface="conversation",
        tool_names=("request_wrap_up",),
    ),
    "quant": Track(
        id="quant",
        name="Quantitative",
        description="Probability, estimation and reasoning questions, worked aloud.",
        surface="conversation",
        tool_names=("request_wrap_up",),
    ),
}


def get_track(track_id: str) -> Track:
    try:
        return TRACKS[track_id]
    except KeyError as exc:
        raise LookupError(f"unknown track {track_id!r}") from exc
