"""Structured end-of-interview report.

The report is produced by a text model from the transcript, final code and rubric, using a JSON
response schema so the UI can render it field by field. `FeedbackGenerator` is a protocol so tests
can use a stub.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .prompts import INTERVIEW_MINUTES

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

_TIMED_NOTE = (
    " A line that starts with [mm:ss] began that long after the interview started; the interview "
    f"is planned for about {INTERVIEW_MINUTES} minutes."
)
_TIMING_RULE = (
    "\n- The transcript has timestamps. Estimate roughly how long the candidate spent on each phase "
    "(clarifying, approach or diagnosis, coding or fixing, testing) and comment on pacing in the "
    "summary or an improvement when it mattered, for example a late start on code or no time left "
    "to test. Do not score pacing as its own dimension."
)


def _stamp(seconds: float) -> str:
    whole = int(seconds)
    return f"[{whole // 60:02d}:{whole % 60:02d}] "


def _render_transcript(transcript: list[dict[str, Any]]) -> tuple[str, bool]:
    """The transcript as CANDIDATE:/INTERVIEWER: lines, and whether any line has a timestamp.

    `t` (seconds since the start) is optional per turn: old saved transcripts have none.
    """
    lines: list[str] = []
    timed = False
    for turn in transcript:
        if not turn.get("text"):
            continue
        t = turn.get("t")
        has_t = isinstance(t, int | float) and not isinstance(t, bool) and t >= 0
        timed = timed or has_t
        lines.append(f"{_stamp(t) if has_t else ''}{turn['role'].upper()}: {turn['text']}")
    return ("\n".join(lines) if lines else "(no transcript captured)"), timed


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
    evidence: str | None = None,
) -> str:
    rubric = "\n".join(f"- {r}" for r in RUBRICS[track_id])
    convo, timed = _render_transcript(transcript)
    extra = ""
    if code and code.strip():
        extra += f"\n\n<final_code>\n{code.strip()}\n</final_code>"
    if test_summary:
        extra += (
            "\n\n<test_suite_result>\n"
            "TEST SUITE RESULT ON THE FINAL CODE (run by the grader after the interview)\n"
            f"{test_summary}\n</test_suite_result>"
        )
    evidence_rule = ""
    if evidence:
        extra += f"\n\n<evidence_digest>\n{evidence}\n</evidence_digest>"
        evidence_rule = (
            "\n- The evidence digest was extracted from the material above by another model, as an index. "
            "It may be incomplete or wrong: check every point against the transcript, final code and test "
            "result, and trust those when they disagree. Quote only from the transcript itself."
        )
    if not test_summary:
        test_rule = ""
    elif track_id == "debug":
        test_rule = (
            "\n- A passing test suite does not prove the root cause was fixed. Check the final code against "
            "the planted bugs in the problem, and judge the candidate's spoken explanation too."
        )
    else:
        test_rule = (
            "\n- The test suite result is the strongest evidence for correctness: failing hidden tests mean "
            "the final code does not fully solve the problem, whatever was said. Passing tests do not "
            "show the candidate's reasoning; judge the other dimensions from the transcript."
        )
    return (
        "<role>\nYou are a senior engineer writing a fair, calibrated report on a mock "
        f"{_TRACK_NOUN.get(track_id, 'technical')} interview. The candidate will read it to improve. "
        "Be specific, honest and kind; do not inflate scores.\n</role>\n\n"
        f"<problem>\n{problem_text}\n</problem>\n\n"
        f"<rubric>\n{rubric}\n</rubric>\n\n"
        "<transcript>\nCANDIDATE lines are the candidate; INTERVIEWER lines are the AI interviewer. "
        "Lines come from speech recognition, so expect small transcription errors."
        f"{_TIMED_NOTE if timed else ''}\n"
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
        "- If the transcript is missing or very short (the candidate spoke only a few times), or most of "
        "the session was off task, say so in the summary. Then no dimension scores above 2 and the "
        "overall score is at most 2: a few good sentences are not enough evidence for a higher score.\n"
        "- Judge the candidate, not the interviewer. Hints the interviewer gave lower the score of the "
        "dimension they helped with.\n"
        "- The overall score reflects the whole interview; correctness and process weigh most. It is "
        f"not a plain average.{test_rule}{_TIMING_RULE if timed else ''}{evidence_rule}\n"
        "</grading_rules>\n\n"
        "Based on the material above, write the report.\n"
        "- summary: two sentences.\n"
        "- dimensions: one entry per rubric dimension, in rubric order. name is the text before the colon "
        "in the rubric entry. justification cites specific evidence, quoting or closely paraphrasing "
        "the transcript.\n"
        "- strengths and improvements: up to three each, specific to this interview; improvements are "
        "actions to take next time.\n"
        "- model_answer_sketch: a few plain sentences on what a strong answer looks like.\n"
        "- notable_moments: up to three, each with a quote copied word for word from a CANDIDATE line "
        "(without the label or timestamp) and why it mattered. Each quote comes from one line; never join "
        "two lines. Leave the list empty rather than invent a quote."
    )


def _norm_quote(text: str) -> str:
    text = text.translate(str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'}))
    return re.sub(r"\s+", " ", text).strip()


def drop_unverified_quotes(report: FeedbackReport, transcript: list[dict[str, Any]]) -> FeedbackReport:
    """Keep only notable moments whose quote appears word for word in a single CANDIDATE line.

    Models sometimes stitch two lines together or fix a word; a report shown to the candidate must
    never put words in their mouth. An ellipsis may join two pieces of the same line. Whitespace and
    curly quotes are normalised; nothing else is forgiven.
    """
    lines = [_norm_quote(str(t.get("text") or "")) for t in transcript if t.get("role") == "candidate"]
    kept = []
    for moment in report.notable_moments:
        quote = _norm_quote(moment.quote).strip("\"'").rstrip(".…").strip()
        pieces = [p.strip(" .") for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if p.strip(" .")]
        if pieces and any(all(p in line for p in pieces) for line in lines):
            kept.append(moment)
        else:
            log.warning(
                "dropping a notable moment whose quote is not in the transcript: %r", moment.quote[:120]
            )
    return report.model_copy(update={"notable_moments": kept})


class TimedPoint(BaseModel):
    time: str = Field(description="mm:ss from the line's [mm:ss] stamp, or empty if lines have no stamps.")
    text: str


class Phase(BaseModel):
    name: str = Field(
        description="e.g. clarify, approach, code, test, complexity; or understand, reproduce, "
        "hypothesise, fix, verify, explain for debugging."
    )
    start: str = Field(description="mm:ss of the first line in this phase, or empty.")
    end: str = Field(description="mm:ss of the last line in this phase, or empty.")
    what_happened: str = Field(description="One or two plain sentences, facts only.")


class EvidenceDigest(BaseModel):
    """Stage 1 of the two-stage report: facts pulled from the interview, no judgement."""

    phases: list[Phase] = Field(description="The phases that actually happened, in order.")
    candidate_quotes: list[TimedPoint] = Field(
        description="Up to 12 important CANDIDATE lines or parts of lines, copied character for character."
    )
    hints_given: list[TimedPoint] = Field(
        description="Each hint or leading question the interviewer gave, in its own words; empty if none."
    )
    test_runs: list[TimedPoint] = Field(
        description="Each test run mentioned in the transcript and its result, plus the final grading run."
    )
    final_code_state: str = Field(
        description="Two or three sentences on what the final code does and whether it solves the problem, "
        "based on the code and the test result."
    )
    off_task_turns: list[TimedPoint] = Field(
        description="CANDIDATE lines unrelated to the interview, copied exactly; empty if none."
    )
    complexity_stated: str = Field(
        description="What the candidate said about time and space complexity, or 'not stated'."
    )


def build_evidence_prompt(
    *,
    track_id: str,
    problem_text: str,
    transcript: list[dict[str, Any]],
    code: str | None,
    test_summary: str | None = None,
) -> str:
    convo, timed = _render_transcript(transcript)
    extra = f"\n\n<final_code>\n{code.strip()}\n</final_code>" if code and code.strip() else ""
    if test_summary:
        extra += f"\n\n<test_suite_result>\nRUN BY THE GRADER ON THE FINAL CODE\n{test_summary}\n</test_suite_result>"
    return (
        "<role>\nYou extract evidence from a mock "
        f"{_TRACK_NOUN.get(track_id, 'technical')} interview for a grader. You do not grade. You record "
        "only what is in the material below.\n</role>\n\n"
        f"<problem>\n{problem_text}\n</problem>\n\n"
        "<transcript>\nCANDIDATE lines are the candidate; INTERVIEWER lines are the AI interviewer."
        f"{_TIMED_NOTE if timed else ''}\n{convo}\n</transcript>{extra}\n\n"
        "<rules>\n"
        "- Never invent, infer or embellish. If something did not happen, leave the list empty or say "
        "'not stated'.\n"
        "- Copy quotes character for character from CANDIDATE lines, without the label or timestamp. Do "
        "not fix grammar, join lines or paraphrase inside a quote.\n"
        "- Attribute carefully: something the interviewer said is not something the candidate did.\n"
        "- Use the [mm:ss] stamps for times; leave times empty when lines have no stamps.\n"
        "</rules>\n\n"
        "Based on the material above, fill in the evidence digest."
    )


def render_evidence(digest: EvidenceDigest) -> str:
    """The digest as plain text for the grader prompt."""

    def points(items: list[TimedPoint]) -> str:
        return "\n".join(f"- {f'[{p.time}] ' if p.time else ''}{p.text}" for p in items) or "- none"

    phases = "\n".join(
        f"- {ph.name} ({ph.start or '?'}-{ph.end or '?'}): {ph.what_happened}" for ph in digest.phases
    )
    return (
        f"PHASES\n{phases or '- none'}\n\nCANDIDATE QUOTES\n{points(digest.candidate_quotes)}\n\n"
        f"HINTS GIVEN\n{points(digest.hints_given)}\n\nTEST RUNS\n{points(digest.test_runs)}\n\n"
        f"FINAL CODE STATE\n{digest.final_code_state}\n\nCOMPLEXITY STATED\n{digest.complexity_stated}\n\n"
        f"OFF-TASK TURNS\n{points(digest.off_task_turns)}"
    )


async def _structured(client: Any, model: str, prompt: str, schema: type[BaseModel]) -> Any:
    """One JSON-schema call to a Gemini text model, parsed into `schema`."""
    from google.genai import types  # imported lazily so tests don't need the SDK

    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            # No temperature: Gemini 3.6+ ignores custom sampling values (Google prompting guide).
        ),
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, schema):
        return parsed
    return schema.model_validate(json.loads(response.text))


class TwoStageFeedbackGenerator:
    """REPORT_MODE=two_stage: `extract_model` writes an evidence digest, then `grade_model` writes the
    report from the digest plus the full material (the digest alone would lose information)."""

    def __init__(self, client: Any, *, extract_model: str, grade_model: str) -> None:
        self._client = client
        self._extract_model = extract_model
        self._grade_model = grade_model

    async def generate(
        self,
        *,
        track_id: str,
        problem_text: str,
        transcript: list[dict[str, Any]],
        code: str | None,
        test_summary: str | None = None,
    ) -> FeedbackReport:
        material = {
            "track_id": track_id,
            "problem_text": problem_text,
            "transcript": transcript,
            "code": code,
            "test_summary": test_summary,
        }
        digest = await _structured(
            self._client, self._extract_model, build_evidence_prompt(**material), EvidenceDigest
        )
        prompt = build_feedback_prompt(**material, evidence=render_evidence(digest))
        return await _structured(self._client, self._grade_model, prompt, FeedbackReport)


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
        prompt = build_feedback_prompt(
            track_id=track_id,
            problem_text=problem_text,
            transcript=transcript,
            code=code,
            test_summary=test_summary,
        )
        return await _structured(self._client, self._model, prompt, FeedbackReport)


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
