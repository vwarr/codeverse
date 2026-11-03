"""Structured end-of-interview report.

The report is produced by a text model from the transcript, final code and rubric, using a JSON
response schema so the UI can render it field by field. `FeedbackGenerator` is a protocol so tests
(and the fake voice backend) can use a stub.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class Dimension(BaseModel):
    name: str
    score: int = Field(ge=1, le=5)
    justification: str


class NotableMoment(BaseModel):
    quote: str
    comment: str


class FeedbackReport(BaseModel):
    overall_score: int = Field(ge=1, le=5)
    summary: str
    dimensions: list[Dimension]
    strengths: list[str]
    improvements: list[str]
    model_answer_sketch: str
    notable_moments: list[NotableMoment] = Field(default_factory=list)


RUBRICS: dict[str, list[str]] = {
    "swe": [
        "Communication: thinking aloud, clarity, responding to questions",
        "Problem decomposition: clarifying questions, choosing an approach, handling edge cases",
        "Correctness: does the final code solve the problem",
        "Complexity analysis: accurate time and space reasoning",
        "Code quality: naming, structure, idiomatic use of the language",
    ],
    "debug": [
        "Communication: narrating hypotheses and reasoning aloud, explaining the root cause clearly",
        "Reproduction and evidence: running the tests or building a failing case before changing code, reading failures carefully",
        "Hypothesis-driven process: forming one testable hypothesis at a time instead of guessing or changing several things at once",
        "Root cause and fix quality: fixing the underlying cause of every planted bug, not the symptom, without breaking anything else",
        "Verification and prevention: rerunning tests after the fix and proposing how to stop this class of bug recurring",
    ],
}


class FeedbackGenerator(Protocol):
    async def generate(
        self,
        *,
        track_id: str,
        problem_text: str,
        transcript: list[dict[str, Any]],
        code: str | None,
        test_summary: str | None = None,
    ) -> FeedbackReport: ...


def build_feedback_prompt(
    *,
    track_id: str,
    problem_text: str,
    transcript: list[dict[str, Any]],
    code: str | None,
    test_summary: str | None = None,
) -> str:
    rubric = "\n".join(f"- {r}" for r in RUBRICS[track_id])
    lines = [f"{t['role'].upper()}: {t['text']}" for t in transcript if t.get("text")]
    convo = "\n".join(lines) if lines else "(no transcript captured)"
    code_block = f"\n\nFINAL CODE\n{code.strip()}" if code and code.strip() else ""
    if test_summary:
        code_block += (
            "\n\nTEST SUITE RESULT ON THE FINAL CODE (run by the grader after the interview)\n"
            f"{test_summary}\nA passing suite does not prove the root cause was fixed; check the final code "
            "against the planted bugs in PROBLEM and judge the candidate's explanation too."
        )
    return (
        "You are grading a mock interview. Be specific and honest; cite what the candidate actually said. "
        "Scores are 1 (poor) to 5 (strong hire). Do not inflate.\n\n"
        f"PROBLEM\n{problem_text}\n\nRUBRIC (one dimension per entry, in this order)\n{rubric}\n\n"
        f"TRANSCRIPT\n{convo}{code_block}\n\n"
        "Return: overall_score, a two-sentence summary, one entry per rubric dimension with a score and a "
        "one-line justification quoting or paraphrasing the transcript, three strengths, three concrete "
        "improvements phrased as actions, a short sketch of what a strong answer looks like, and up to "
        "three notable moments (a short quote and why it mattered)."
    )


class GeminiFeedbackGenerator:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self,
        *,
        track_id: str,
        problem_text: str,
        transcript: list[dict[str, Any]],
        code: str | None,
        test_summary: str | None = None,
    ) -> FeedbackReport:
        from google.genai import types  # imported lazily so tests don't need the SDK

        prompt = build_feedback_prompt(
            track_id=track_id,
            problem_text=problem_text,
            transcript=transcript,
            code=code,
            test_summary=test_summary,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FeedbackReport,
                temperature=0.3,
            ),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, FeedbackReport):
            return parsed
        return FeedbackReport.model_validate(json.loads(response.text))


class StaticFeedbackGenerator:
    """Used with the fake voice backend and in tests."""

    def __init__(self, report: FeedbackReport | None = None) -> None:
        self.report = report or FeedbackReport(
            overall_score=3,
            summary="Stub report: no model was consulted.",
            dimensions=[Dimension(name="Communication", score=3, justification="stub")],
            strengths=["stub"],
            improvements=["stub"],
            model_answer_sketch="stub",
        )
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        track_id: str,
        problem_text: str,
        transcript: list[dict[str, Any]],
        code: str | None,
        test_summary: str | None = None,
    ) -> FeedbackReport:
        self.calls.append(
            {
                "track_id": track_id,
                "problem_text": problem_text,
                "transcript": transcript,
                "code": code,
                "test_summary": test_summary,
            }
        )
        return self.report
