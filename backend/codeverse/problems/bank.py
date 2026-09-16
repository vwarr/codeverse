"""Problem bank: the single source of truth for interview questions.

Loaded from bank.json at import time and validated with pydantic, so a malformed
entry fails at startup rather than mid-interview.
"""

from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Track = Literal["swe", "ib", "quant"]
Difficulty = Literal["easy", "medium", "hard"]

BANK_PATH = Path(__file__).with_name("bank.json")


class Example(BaseModel):
    input: str
    output: str
    explanation: str | None = None


class TestCase(BaseModel):
    """Phase 4 will execute these. `args` are positional arguments to the solution."""

    args: list[object]
    expected: object


class Problem(BaseModel):
    id: str
    track: Track
    title: str
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)
    statement: str  # markdown
    examples: list[Example] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    starter_code: dict[str, str] = Field(default_factory=dict)  # language -> code
    hints: list[str] = Field(default_factory=list)
    tests: list[TestCase] = Field(default_factory=list)
    function_name: str | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(f"problem id must be a slug, got {v!r}")
        return v

    def prompt_text(self) -> str:
        """The problem as the interviewer sees it (plain text, read by the model)."""
        parts = [f"Title: {self.title}", f"Difficulty: {self.difficulty}", "", self.statement.strip()]
        if self.examples:
            parts.append("")
            for i, ex in enumerate(self.examples, 1):
                line = f"Example {i}: input {ex.input} -> output {ex.output}"
                if ex.explanation:
                    line += f" ({ex.explanation})"
                parts.append(line)
        if self.constraints:
            parts.append("")
            parts.append("Constraints: " + "; ".join(self.constraints))
        if self.hints:
            parts.append("")
            parts.append(
                "Hints you may offer, in order, only if the candidate is stuck: " + " | ".join(self.hints)
            )
        return "\n".join(parts)

    def public(self) -> dict:
        """What the frontend gets: everything except hints and hidden tests."""
        return self.model_dump(exclude={"hints", "tests"})


class ProblemBank:
    def __init__(self, problems: list[Problem]) -> None:
        ids = [p.id for p in problems]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate problem ids: {sorted(dupes)}")
        self._by_id = {p.id: p for p in problems}

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, problem_id: str) -> Problem | None:
        return self._by_id.get(problem_id)

    def list(self, *, track: Track | None = None, difficulty: Difficulty | None = None) -> list[Problem]:
        out = [
            p
            for p in self._by_id.values()
            if (track is None or p.track == track) and (difficulty is None or p.difficulty == difficulty)
        ]
        return sorted(out, key=lambda p: ({"easy": 0, "medium": 1, "hard": 2}[p.difficulty], p.title))

    def random(
        self, *, track: Track, difficulty: Difficulty | None = None, rng: random.Random | None = None
    ) -> Problem:
        candidates = self.list(track=track, difficulty=difficulty)
        if not candidates:
            raise LookupError(f"no problems for track={track} difficulty={difficulty}")
        return (rng or random).choice(candidates)


def load_bank(path: Path = BANK_PATH) -> ProblemBank:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return ProblemBank([Problem.model_validate(item) for item in raw])


@lru_cache
def get_bank() -> ProblemBank:
    return load_bank()
