"""REPORT_MODE: single and two-stage report generation, with a fake genai client (no network)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from codeverse.config import Settings
from codeverse.interview.feedback import (
    EvidenceDigest,
    FeedbackReport,
    GeminiFeedbackGenerator,
    NotableMoment,
    TwoStageFeedbackGenerator,
    build_evidence_prompt,
    build_feedback_prompt,
    drop_unverified_quotes,
)
from codeverse.web.service import feedback_factory

pytest.importorskip("google.genai")

DIGEST = {
    "phases": [{"name": "approach", "start": "00:52", "end": "03:10", "what_happened": "Chose a hash map."}],
    "candidate_quotes": [{"time": "01:35", "text": "I'd keep a hash map from value to index"}],
    "hints_given": [],
    "test_runs": [{"time": "07:50", "text": "3 of 3 passed"}],
    "final_code_state": "One-pass hash map; solves the problem.",
    "off_task_turns": [],
    "complexity_stated": "O(n) time, O(n) space",
}
REPORT = {
    "overall_score": 4,
    "summary": "Good.",
    "dimensions": [{"name": "Communication", "score": 4, "justification": "clear"}],
    "strengths": [],
    "improvements": [],
    "model_answer_sketch": "hash map",
    "notable_moments": [],
}
MATERIAL = {
    "track_id": "swe",
    "problem_text": "Two Sum",
    "transcript": [{"role": "candidate", "text": "I'd keep a hash map from value to index", "t": 95.0}],
    "code": "def two_sum(nums, target): ...",
    "test_summary": "3 of 3 tests passed.",
}


class FakeClient:
    """Stands in for genai.Client: records each call and answers by response schema."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model: str, contents: str, config: Any) -> Any:
        schema = config.response_schema
        self.calls.append({"model": model, "prompt": contents, "schema": schema})
        body = DIGEST if schema is EvidenceDigest else REPORT
        return SimpleNamespace(parsed=None, text=json.dumps(body))


def test_two_stage_extracts_with_one_model_and_grades_with_another() -> None:
    client = FakeClient()
    gen = TwoStageFeedbackGenerator(client, extract_model="lite", grade_model="grader")
    report = asyncio.run(gen.generate(**MATERIAL))
    assert isinstance(report, FeedbackReport) and report.overall_score == 4
    extract, grade = client.calls
    assert (extract["model"], extract["schema"]) == ("lite", EvidenceDigest)
    assert (grade["model"], grade["schema"]) == ("grader", FeedbackReport)
    # The grader gets the digest AND the full material.
    assert "<evidence_digest>" in grade["prompt"] and "[01:35] I'd keep a hash map" in grade["prompt"]
    assert "[01:35] CANDIDATE: I'd keep a hash map from value to index" in grade["prompt"]
    assert "<final_code>" in grade["prompt"] and "3 of 3 tests passed." in grade["prompt"]
    assert "trust those when they disagree" in grade["prompt"]


def test_evidence_prompt_forbids_invention_and_does_not_grade() -> None:
    text = build_evidence_prompt(**MATERIAL)
    assert "Never invent" in text and "character for character" in text and "You do not grade" in text
    assert "<score_anchors>" not in text and "3 of 3 tests passed." in text


def test_single_stage_prompt_has_no_digest() -> None:
    assert "<evidence_digest>" not in build_feedback_prompt(**MATERIAL)


def test_feedback_factory_follows_report_mode() -> None:
    client = FakeClient()
    single = feedback_factory(Settings(_env_file=None), lambda: client)("main")
    assert isinstance(single, GeminiFeedbackGenerator)
    asyncio.run(single.generate(**MATERIAL))
    assert [c["model"] for c in client.calls] == ["main"]

    client = FakeClient()
    settings = Settings(_env_file=None, report_mode="two_stage", report_extract_model="lite")
    two = feedback_factory(settings, lambda: client)("main")
    assert isinstance(two, TwoStageFeedbackGenerator)
    asyncio.run(two.generate(**MATERIAL))
    assert [c["model"] for c in client.calls] == ["lite", "main"]


def test_report_mode_defaults_to_single() -> None:
    assert Settings.model_fields["report_mode"].default == "single"
    assert Settings.model_fields["gemini_text_model"].default == "gemini-3.6-flash"


def test_unverified_quotes_are_dropped() -> None:
    transcript = [
        {"role": "candidate", "text": "Oh, that's wrong, it uses the same element twice."},
        {"role": "candidate", "text": "Let me change it to one loop."},
        {"role": "interviewer", "text": "How might you fix that?"},
        {"role": "candidate", "text": "I\u2019d keep a  hash map, then check   each complement first."},
    ]
    quotes = [
        "Oh, that's wrong, it uses the same element twice.",  # verbatim
        '"Let me change it to one loop"',  # wrapped in quotes, no final period
        "I'd keep a hash map ... check each complement first",  # curly quote, spaces, ellipsis in one line
        "Oh, that's wrong, it uses the same element twice. Let me change it to one loop.",  # two lines joined
        "How might you fix that?",  # the interviewer's words
        "Let me change it to two loops.",  # altered
    ]
    report = FeedbackReport.model_validate(
        {**REPORT, "notable_moments": [{"quote": q, "comment": "c"} for q in quotes]}
    )
    kept = drop_unverified_quotes(report, transcript).notable_moments
    assert [m.quote for m in kept] == quotes[:3]
    assert all(isinstance(m, NotableMoment) for m in kept) and len(report.notable_moments) == 6
