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

from pydantic import BaseModel, Field, field_validator, model_validator

Track = Literal["swe", "debug"]
Difficulty = Literal["easy", "medium", "hard"]
Compare = Literal["exact", "any_order"]

BANK_PATH = Path(__file__).with_name("bank.json")
# Debugging problems are whole Python modules plus tests, so they live as real files
# (one directory each) rather than as strings inside bank.json. See debug/README.md.
DEBUG_DIR = Path(__file__).with_name("debug")


class Example(BaseModel):
    input: str
    output: str
    explanation: str | None = None


class TestCase(BaseModel):
    """One hidden case for a swe problem. `args` are positional arguments to `function_name`."""

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
    # How a swe test compares the result with `expected`. "any_order": the problem accepts the
    # items of the returned list in any order (e.g. two-sum may return [1, 0]).
    compare: Compare = "exact"
    # Debug track only. The buggy module is starter_code["python"]; these stay server-side.
    module_name: str | None = None  # file name (without .py) the tests import from
    test_code: str | None = None  # stdlib unittest source, run by the Run button
    reference_solution: str | None = None  # the fixed module; CI proves the tests pass on it
    bugs: list[str] = Field(default_factory=list)  # what is planted, for the interviewer and grader

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(f"problem id must be a slug, got {v!r}")
        return v

    @model_validator(mode="after")
    def _debug_complete(self) -> Problem:
        if self.track == "debug":
            missing = [
                name
                for name, value in (
                    ("module_name", self.module_name),
                    ("test_code", self.test_code),
                    ("reference_solution", self.reference_solution),
                    ("starter_code.python", self.starter_code.get("python")),
                    ("bugs", self.bugs),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"debug problem {self.id!r} is missing {', '.join(missing)}")
            if not self.module_name.isidentifier():  # type: ignore[union-attr]
                raise ValueError(f"module_name must be a Python identifier, got {self.module_name!r}")
        return self

    @model_validator(mode="after")
    def _swe_tests_callable(self) -> Problem:
        if self.tests and not (self.function_name and self.function_name.isidentifier()):
            raise ValueError(f"problem {self.id!r} has tests but no valid function_name")
        return self

    @property
    def has_tests(self) -> bool:
        """The Run button has a hidden suite for this problem (see execution/jobs.py)."""
        if self.track == "debug":
            return bool(self.module_name and self.test_code)
        return bool(self.tests and self.function_name)

    def prompt_text(self) -> str:
        """The problem as the interviewer sees it (plain text, read by the model)."""
        if self.track == "debug":
            return self._debug_prompt_text()
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

    def _debug_prompt_text(self) -> str:
        parts = [
            f"Title: {self.title}",
            f"Difficulty: {self.difficulty}",
            f"Module: {self.module_name}.py",
            "",
            "BUG REPORT (the candidate sees this)",
            self.statement.strip(),
        ]
        if self.constraints:
            parts += ["", "Constraints (the candidate sees these): " + "; ".join(self.constraints)]
        parts += [
            "",
            "ORIGINAL CODE (preloaded in the candidate's editor; the candidate may since have changed it)",
            self.starter_code["python"].rstrip(),
            "",
            f"PLANTED BUGS ({len(self.bugs)}) — for you only; never reveal, name or point at them:",
        ]
        parts += [f"{i}. {b}" for i, b in enumerate(self.bugs, 1)]
        if self.hints:
            parts.append("")
            parts.append(
                "Hints you may offer, in order, only if the candidate is stuck: " + " | ".join(self.hints)
            )
        return "\n".join(parts)

    def public(self) -> dict:
        """What the frontend gets: everything except hints, tests and the debug answer key."""
        data = self.model_dump(
            exclude={"hints", "tests", "test_code", "reference_solution", "bugs", "compare"}
        )
        data["has_tests"] = self.has_tests
        return data


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


def load_debug_problem(directory: Path) -> Problem:
    """Read one debug problem directory: problem.json + buggy.py + fixed.py + test_<module>.py."""
    meta = json.loads((directory / "problem.json").read_text(encoding="utf-8"))
    module = meta["module_name"]
    meta.setdefault("id", directory.name)
    meta["track"] = "debug"
    meta["starter_code"] = {"python": (directory / "buggy.py").read_text(encoding="utf-8")}
    meta["reference_solution"] = (directory / "fixed.py").read_text(encoding="utf-8")
    meta["test_code"] = (directory / f"test_{module}.py").read_text(encoding="utf-8")
    return Problem.model_validate(meta)


def load_bank(path: Path = BANK_PATH, debug_dir: Path | None = DEBUG_DIR) -> ProblemBank:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    problems = [Problem.model_validate(item) for item in raw]
    if debug_dir is not None and debug_dir.is_dir():
        problems += [
            load_debug_problem(d) for d in sorted(debug_dir.iterdir()) if (d / "problem.json").is_file()
        ]
    return ProblemBank(problems)


@lru_cache
def get_bank() -> ProblemBank:
    return load_bank()
