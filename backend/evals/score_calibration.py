"""Score calibration eval for the report model. Manual only: it calls the real Gemini text model.

Each fixture in evals/fixtures/ is a synthetic interview (transcript, final code, expected score
bands). The script builds the report the way /api/report does: the same prompt builder and
generator, and a real test run of the fixture code (both tracks grade the final run).
It runs every case --runs times and checks:

- the overall score is inside the expected band, and per-dimension scores inside theirs;
- the overall score varies by at most one point across runs;
- every notable_moments quote appears word for word in the transcript.

Usage (from backend/; reads GEMINI_API_KEY from backend/.env):

    uv run python evals/score_calibration.py                         # 8 cases x 1 run on gemini-3.8-flash
    uv run python evals/score_calibration.py --runs 3 --max-calls 30 # variance check: 24 calls
    uv run python evals/score_calibration.py --case swe-strong --case swe-poor

Quota. Free-tier quotas are per model and per day (gemini-3.6-flash and gemini-3.8-flash: 20 a
day, 5 a minute), and the key is shared with production. So the default model is
gemini-3.8-flash, not the production report model (GEMINI_TEXT_MODEL, gemini-3.6-flash), and every
API request, retries included, counts against --max-calls (default 12). The planned call count
(cases x runs) is printed before any call, and a run that would exceed the budget is refused.
Calibrating the production model itself means `--model gemini-3.6-flash` with a small budget, for
example `--case swe-mediocre --max-calls 3`: every call there comes out of the 20 a day that
production reports need. gemini-3.8-flash is also the first production fallback, so a large eval
run on it shrinks that fallback for the day too.

A per-day 429 stops the run at once. Each report is appended to a JSONL file in evals/results/
(git-ignored) as soon as it arrives, so an interrupted run keeps what it got. Exits 1 if any check
fails.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any

from codeverse.config import get_settings
from codeverse.execution import LocalRunner, job_for
from codeverse.interview.feedback import RUBRICS, FeedbackReport, GeminiFeedbackGenerator
from codeverse.interview.tracks import get_track
from codeverse.problems.bank import get_bank
from codeverse.web.service import is_transient

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
RESULTS = HERE / "results"
RETRY_DELAYS = (20.0, 60.0)
MAX_OVERALL_SPREAD = 1
DEFAULT_MODEL = "gemini-3.8-flash"


class CallBudget:
    """Every API request, retries included, takes one call; past the cap the run stops."""

    def __init__(self, cap: int) -> None:
        self.cap, self.used = cap, 0

    def take(self) -> None:
        if self.used >= self.cap:
            raise BudgetExhausted(f"call budget of {self.cap} used up")
        self.used += 1


class BudgetExhausted(Exception):
    pass


class DailyQuotaExhausted(BudgetExhausted):
    """A per-day 429. The key may be shared with production, so the eval stops at once."""


def _quota_id(exc: BaseException) -> str:
    match = re.search(r"'quotaId': '([^']+)'", str(exc))
    return match.group(1) if match else str(exc)[:80]


def is_daily_quota(exc: BaseException) -> bool:
    text = str(exc)
    return "PerDay" in text or "per day" in text.lower()


def load_fixtures(names: list[str] | None) -> list[dict[str, Any]]:
    fixtures = [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("*.json"))]
    if names:
        unknown = set(names) - {f["name"] for f in fixtures}
        if unknown:
            raise SystemExit(f"unknown case(s): {', '.join(sorted(unknown))}")
        fixtures = [f for f in fixtures if f["name"] in names]
    return fixtures


def _norm(text: str) -> str:
    """Whitespace-collapsed text with straight quotes, for the verbatim-quote check."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def quote_problems(report: FeedbackReport, transcript: list[dict[str, Any]]) -> list[str]:
    candidate = [_norm(t["text"]) for t in transcript if t["role"] == "candidate"]
    anyone = [_norm(t["text"]) for t in transcript]
    problems = []
    for moment in report.notable_moments:
        quote = _norm(moment.quote).strip("\"'").rstrip(".…").strip()
        # Allow an ellipsis joining two verbatim pieces of one line.
        pieces = [p.strip(" .") for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if p.strip(" .")]
        if any(all(p in line for p in pieces) for line in candidate):
            continue
        where = "an INTERVIEWER line" if any(all(p in line for p in pieces) for line in anyone) else "nowhere"
        problems.append(f"quote found in {where}: {moment.quote!r}")
    return problems


def dimension_scores(report: FeedbackReport, track_id: str) -> dict[str, int]:
    names = [r.split(":", 1)[0] for r in RUBRICS[track_id]]
    scores: dict[str, int] = {}
    for dim in report.dimensions:
        match = next((n for n in names if dim.name.strip().lower().startswith(n.lower())), None)
        if match is not None:
            scores[match] = dim.score
    return scores


def check_run(fixture: dict[str, Any], report: FeedbackReport) -> list[str]:
    exp = fixture["expected"]
    failures = []
    lo, hi = exp["overall"]
    if not lo <= report.overall_score <= hi:
        failures.append(f"overall {report.overall_score} outside {lo}-{hi}")
    scores = dimension_scores(report, fixture["track"])
    names = [r.split(":", 1)[0] for r in RUBRICS[fixture["track"]]]
    missing = [n for n in names if n not in scores]
    if missing or len(report.dimensions) != len(names):
        failures.append(
            f"dimensions do not match the rubric (missing {missing}, got {len(report.dimensions)})"
        )
    for name, (dlo, dhi) in exp.get("dimensions", {}).items():
        if name in scores and not dlo <= scores[name] <= dhi:
            failures.append(f"{name} {scores[name]} outside {dlo}-{dhi}")
    cap = exp.get("max_dimension")
    if cap is not None:
        over = {n: s for n, s in scores.items() if s > cap}
        if over:
            failures.append(f"dimensions above {cap}: {over}")
    failures += quote_problems(report, fixture["transcript"])
    return failures


async def final_run_summary(fixture: dict[str, Any]) -> tuple[str | None, str]:
    """(test summary for the grader or None, a one-line fixture sanity note). Also checks the
    fixture code really passes or fails as the fixture says, so a broken fixture is caught early."""
    problem = get_bank().get(fixture["problem_id"])
    if problem is None:
        raise SystemExit(f"{fixture['name']}: unknown problem {fixture['problem_id']!r}")
    job = job_for(problem, fixture["code"], time_limit=get_settings().code_run_timeout_seconds)
    if job is None:
        return None, "no tests"
    result = await LocalRunner().run(job)
    passed = result.total > 0 and result.passed == result.total
    want = fixture["expected"].get("final_tests")
    if want and (want == "pass") != passed:
        raise SystemExit(
            f"{fixture['name']}: fixture code should {want} but got {result.passed}/{result.total}"
        )
    # Mirror production: only tracks that grade the final run show the result to the grader.
    summary = result.summary(max_failures=12) if get_track(fixture["track"]).grade_final_run else None
    return summary, f"{result.passed}/{result.total} tests"


async def generate(
    gen: GeminiFeedbackGenerator, fixture: dict[str, Any], summary: str | None, budget: CallBudget
) -> FeedbackReport:
    problem = get_bank().get(fixture["problem_id"])
    assert problem is not None
    for attempt in range(len(RETRY_DELAYS) + 1):
        budget.take()
        try:
            return await gen.generate(
                track_id=fixture["track"],
                problem_text=problem.prompt_text(),
                transcript=fixture["transcript"],
                code=fixture["code"],
                test_summary=summary,
            )
        except Exception as exc:  # noqa: BLE001
            if is_daily_quota(exc):
                raise DailyQuotaExhausted(str(exc)[:300]) from exc
            if attempt == len(RETRY_DELAYS) or not is_transient(exc):
                raise
            print(
                f"  {fixture['name']}: transient error ({_quota_id(exc)}), retrying in {RETRY_DELAYS[attempt]}s",
                file=sys.stderr,
            )
            await asyncio.sleep(RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=1, help="runs per case (default 1)")
    parser.add_argument(
        "--max-calls",
        type=int,
        default=12,
        help="most API requests to make, retries included (default 12)",
    )
    parser.add_argument("--case", action="append", help="run only this case (repeatable)")
    parser.add_argument("--concurrency", type=int, default=2, help="parallel model calls (default 2)")
    parser.add_argument(
        "--interval",
        type=float,
        default=13.0,
        help="minimum seconds between call starts (default 13: the free tier allows 5 a minute)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EVAL_GEMINI_MODEL") or DEFAULT_MODEL,
        help=f"text model to grade with (default: $EVAL_GEMINI_MODEL or {DEFAULT_MODEL})",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set (backend/.env)")
    from google import genai

    fixtures = load_fixtures(args.case)
    planned = len(fixtures) * args.runs
    print(
        f"plan: {len(fixtures)} case(s) x {args.runs} run(s) = {planned} call(s) on {args.model}, "
        f"budget {args.max_calls} (retries count)"
    )
    if args.model == settings.gemini_text_model:
        print(f"warning: {args.model} is the production report model; these calls use its daily quota")
    if planned > args.max_calls:
        raise SystemExit(f"{planned} planned calls exceed --max-calls {args.max_calls}; no calls made")
    budget = CallBudget(args.max_calls)
    gen = GeminiFeedbackGenerator(genai.Client(api_key=settings.gemini_api_key), args.model)
    summaries = {}
    for f in fixtures:
        summaries[f["name"]] = await final_run_summary(f)
        print(f"fixture {f['name']}: {len(f['transcript'])} turns, code {summaries[f['name']][1]}")
    print(f"model {args.model}, {args.runs} run(s) per case\n")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    print(f"raw reports: {out}\n")

    sem = asyncio.Semaphore(args.concurrency)
    pace = asyncio.Lock()
    stop = asyncio.Event()  # set on a per-day 429: skip every remaining call

    async def one(fixture: dict[str, Any], run: int) -> tuple[str, int, FeedbackReport | str]:
        async with sem:
            async with pace:  # space out call starts to stay under the per-minute quota
                await asyncio.sleep(args.interval if run or fixture is not fixtures[0] else 0)
            if stop.is_set():
                return fixture["name"], run, "skipped: run stopped (budget or daily quota)"
            try:
                report: FeedbackReport | str = await generate(
                    gen, fixture, summaries[fixture["name"]][0], budget
                )
            except BudgetExhausted as exc:
                stop.set()
                print(f"STOPPING: {exc}", file=sys.stderr)
                report = f"error: {str(exc)[:120]}"
            except Exception as exc:  # noqa: BLE001
                report = f"error: {str(exc)[:200]}"
            score = report if isinstance(report, str) else f"overall {report.overall_score}"
            print(f"  done {fixture['name']} run {run + 1}: {score}", file=sys.stderr)
            with out.open("a") as fh:  # saved as it arrives, so an interrupted run keeps its results
                record = report if isinstance(report, str) else report.model_dump()
                fh.write(json.dumps({"case": fixture["name"], "run": run + 1, "report": record}) + "\n")
            return fixture["name"], run, report

    results = await asyncio.gather(*(one(f, r) for f in fixtures for r in range(args.runs)))
    by_case: dict[str, list[FeedbackReport | str]] = {}
    for name, _, report in sorted(results, key=lambda x: (x[0], x[1])):
        by_case.setdefault(name, []).append(report)

    failed = False
    saved: dict[str, Any] = {"model": args.model, "runs": args.runs, "cases": {}}
    header = f"{'case':<17} {'band':>5} {'overall':<10} {'mean':>5}  dimensions (one row per run)"
    print(header)
    print("-" * len(header))
    for fixture in fixtures:
        name = fixture["name"]
        errors = [r for r in by_case[name] if isinstance(r, str)]
        reports = [r for r in by_case[name] if not isinstance(r, str)]
        lo, hi = fixture["expected"]["overall"]
        case_fail = [f"model call failed: {e}" for e in errors]
        if not reports:
            print(f"{name:<17} no reports")
            for msg in case_fail:
                print(f"    - {msg}")
            failed = True
            continue
        overall = [r.overall_score for r in reports]
        for i, report in enumerate(reports, 1):
            case_fail += [f"run {i}: {msg}" for msg in check_run(fixture, report)]
        if max(overall) - min(overall) > MAX_OVERALL_SPREAD:
            case_fail.append(
                f"overall spread {min(overall)}-{max(overall)} is more than {MAX_OVERALL_SPREAD}"
            )
        names = [r.split(":", 1)[0] for r in RUBRICS[fixture["track"]]]
        dims = [
            " ".join(str(dimension_scores(r, fixture["track"]).get(n, "?")) for n in names) for r in reports
        ]
        mark = "FAIL" if case_fail else "ok"
        print(
            f"{name:<17} {lo}-{hi:<3} {','.join(map(str, overall)):<10} {statistics.mean(overall):>5.2f}  "
            f"{' | '.join(dims)}  {mark}"
        )
        for msg in case_fail:
            print(f"    - {msg}")
        failed = failed or bool(case_fail)
        saved["cases"][name] = {
            "expected": fixture["expected"],
            "overall": overall,
            "failures": case_fail,
            "reports": [r.model_dump() for r in reports],
        }
    print(
        "\ndimension order:",
        "; ".join(f"{t}: {', '.join(r.split(':')[0] for r in RUBRICS[t])}" for t in RUBRICS),
    )

    summary_path = out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(saved, indent=2))
    print(f"summary: {summary_path}")
    print(f"API requests made: {budget.used} of {budget.cap}")
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
