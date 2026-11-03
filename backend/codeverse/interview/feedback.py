"""Structured end-of-interview report.

The report is produced by a text model from the transcript, final code and rubric, using a JSON
response schema so the UI can render it field by field. `FeedbackGenerator` is a protocol so tests
can use a stub.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class Dimension(BaseModel):
    name: str = Field(description="The rubric dimension name: the text before the colon in the rubric entry.")
    score: int = Field(ge=1, le=5, description="1 to 5, using the score anchors in the prompt.")
    justification: str = Field(
        description="One or two sentences citing specific evidence from the transcript or final code."
    )


class NotableMoment(BaseModel):
    quote: str = Field(description="A short quote copied word for word from the transcript.")
    comment: str = Field(description="One sentence on why this moment mattered.")


class FeedbackReport(BaseModel):
    overall_score: int = Field(
        ge=1, le=5, description="1 to 5 overall, using the score anchors; not a plain average."
    )
    summary: str = Field(description="Two sentences: the overall picture and the deciding factor.")
    dimensions: list[Dimension] = Field(
        description="Exactly one entry per rubric dimension, in rubric order."
    )
    strengths: list[str] = Field(description="Up to three specific strengths, each tied to evidence.")
    improvements: list[str] = Field(
        description="Up to three concrete improvements, each phrased as an action to take next time."
    )
    model_answer_sketch: str = Field(
        description="A short plain-text sketch of what a strong answer looks like for this problem."
    )
    notable_moments: list[NotableMoment] = Field(
        default_factory=list, description="Up to three moments with verbatim quotes; empty if none."
    )


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


_TRACK_NOUN = {"swe": "coding", "debug": "debugging"}


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
    extra = ""
    if code and code.strip():
        extra += f"\n\n<final_code>\n{code.strip()}\n</final_code>"
    if test_summary:
        extra += (
            "\n\n<test_suite_result>\n"
            "TEST SUITE RESULT ON THE FINAL CODE (run by the grader after the interview)\n"
            f"{test_summary}\n</test_suite_result>"
        )
    test_rule = (
        "\n- A passing test suite does not prove the root cause was fixed. Check the final code against "
        "the planted bugs in the problem, and judge the candidate's spoken explanation too."
        if test_summary
        else ""
    )
    return (
        "<role>\nYou are a senior engineer writing a fair, calibrated report on a mock "
        f"{_TRACK_NOUN.get(track_id, 'technical')} interview. The candidate will read it to improve. "
        "Be specific, honest and kind; do not inflate scores.\n</role>\n\n"
        f"<problem>\n{problem_text}\n</problem>\n\n"
        f"<rubric>\n{rubric}\n</rubric>\n\n"
        "<transcript>\nCANDIDATE lines are the candidate; INTERVIEWER lines are the AI interviewer. "
        "Lines come from speech recognition, so expect small transcription errors.\n"
        f"{convo}\n</transcript>{extra}\n\n"
        "<score_anchors>\n"
        "5 = strong: clear, correct and complete with little or no help; would pass a real interview.\n"
        "4 = good: mostly correct and clear, with minor gaps or one small hint.\n"
        "3 = mixed: reached a partial or working result but with real gaps or several hints.\n"
        "2 = weak: major gaps; needed heavy help or the result is mostly wrong.\n"
        "1 = very weak, not attempted, or no evidence for this dimension in the transcript.\n"
        "</score_anchors>\n\n"
        "<grading_rules>\n"
        "- Use only evidence in the transcript, final code and test result above. Never invent events, "
        "quotes, code or test results. If something did not happen, say so.\n"
        "- If there is no evidence for a dimension, score it 1 and say that in the justification.\n"
        "- If the transcript is missing or very short, say so in the summary and keep scores low.\n"
        "- Judge the candidate, not the interviewer. Hints the interviewer gave lower the score of the "
        "dimension they helped with.\n"
        "- The overall score reflects the whole interview; correctness and process weigh most. It is "
        f"not a plain average.{test_rule}\n"
        "</grading_rules>\n\n"
        "Based on the material above, write the report.\n"
        "- summary: two sentences.\n"
        "- dimensions: one entry per rubric dimension, in rubric order. name is the text before the colon "
        "in the rubric entry. justification cites specific evidence, quoting or closely paraphrasing "
        "the transcript.\n"
        "- strengths and improvements: up to three each, specific to this interview; improvements are "
        "actions to take next time.\n"
        "- model_answer_sketch: a few plain sentences on what a strong answer looks like.\n"
        "- notable_moments: up to three, each with a quote copied word for word from a CANDIDATE line and "
        "why it mattered. Leave the list empty rather than invent a quote."
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
                # No temperature: Gemini 3.6+ ignores custom sampling values (Google prompting guide).
            ),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, FeedbackReport):
            return parsed
        return FeedbackReport.model_validate(json.loads(response.text))


class StaticFeedbackGenerator:
    """A fixed report, for tests."""

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
