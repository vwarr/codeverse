"""Compare report setups on the calibration fixtures. Manual only: it calls real Gemini models.

Setups (see the REPORT_MODE setting):
  A  single stage, gemini-3.5-flash-lite, 3 runs per case
  B  single stage, gemini-3.8-flash, 1 run per case (quality reference)
  C  two stage: gemini-3.5-flash-lite extracts evidence, gemini-3.8-flash grades, 1 run per case
  D  two stage, gemini-3.5-flash-lite for both steps, 2 runs per case

Every request goes through a budgeted client: per-model hard caps (retries included), per-model
pacing under the free-tier per-minute limits, and the production report model is never called. A
per-day 429 stops everything. Each report is appended to evals/results/compare-*.jsonl as it arrives.

    uv run python evals/compare_report_setups.py --setup A --setup D   # lite only
    uv run python evals/compare_report_setups.py                       # all four: 64 lite + 16 flash calls
    uv run python evals/compare_report_setups.py --summarize evals/results/compare-<stamp>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import datetime as dt
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from score_calibration import (
    RESULTS,
    _quota_id,
    dimension_scores,
    final_run_summary,
    is_daily_quota,
    load_fixtures,
    quote_problems,
)

from codeverse.config import get_settings
from codeverse.interview.feedback import (
    RUBRICS,
    FeedbackReport,
    GeminiFeedbackGenerator,
    TwoStageFeedbackGenerator,
)
from codeverse.problems.bank import get_bank
from codeverse.web.service import is_transient

LITE, FLASH = "gemini-3.5-flash-lite", "gemini-3.8-flash"
FORBIDDEN = {"gemini-3.6-flash"}  # production's report model: never spend its quota here
CAPS = {LITE: 100, FLASH: 16}
# Seconds between call starts per model: free tier is 15/min for lite, 5/min for 3.8-flash.
INTERVALS = {LITE: 4.5, FLASH: 15.0}
MINUTE_RETRY_DELAY = 30.0


@dataclass(frozen=True)
class Setup:
    key: str
    label: str
    runs: int
    grade_model: str
    extract_model: str | None = None  # None: single stage

    def generator(self, client: Any) -> Any:
        if self.extract_model:
            return TwoStageFeedbackGenerator(
                client, extract_model=self.extract_model, grade_model=self.grade_model
            )
        return GeminiFeedbackGenerator(client, self.grade_model)


SETUPS = {
    "A": Setup("A", "single, lite", 3, LITE),
    "B": Setup("B", "single, 3.8-flash", 1, FLASH),
    "C": Setup("C", "two-stage, lite -> 3.8-flash", 1, FLASH, LITE),
    "D": Setup("D", "two-stage, lite -> lite", 2, LITE, LITE),
}


class Stop(Exception):
    """Budget used up, a forbidden model, or a per-day 429: stop every remaining call."""


_report_calls: contextvars.ContextVar[list[tuple[str, float]]] = contextvars.ContextVar("report_calls")


class BudgetedClient:
    """Wraps genai.Client.aio.models.generate_content with caps, pacing and a stop switch."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.used = dict.fromkeys(CAPS, 0)
        self.stopped: str | None = None
        self._locks = {m: asyncio.Lock() for m in CAPS}
        self._last = dict.fromkeys(CAPS, 0.0)
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _take(self, model: str) -> None:
        if model in FORBIDDEN or model not in CAPS:
            raise Stop(f"model {model} is not allowed in this comparison")
        async with self._locks[model]:
            if self.stopped:
                raise Stop(self.stopped)
            if self.used[model] >= CAPS[model]:
                raise Stop(f"{model}: budget of {CAPS[model]} calls used up")
            wait = self._last[model] + INTERVALS[model] - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[model] = time.monotonic()
            self.used[model] += 1

    async def _generate(self, *, model: str, contents: Any, config: Any) -> Any:
        for attempt in range(3):
            await self._take(model)
            start = time.monotonic()
            try:
                response = await self._real.aio.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:  # noqa: BLE001
                if is_daily_quota(exc):
                    self.stopped = f"per-day quota on {model}: {_quota_id(exc)}"
                    raise Stop(self.stopped) from exc
                if is_transient(exc) and attempt < 2:  # 429 per minute or 503; retries count
                    print(
                        f"  {model}: transient ({_quota_id(exc)}), retrying in {MINUTE_RETRY_DELAY}s",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(MINUTE_RETRY_DELAY)
                    continue
                raise
            _report_calls.get().append((model, time.monotonic() - start))
            return response
        raise AssertionError("unreachable")


def score_report(fixture: dict[str, Any], report: FeedbackReport) -> dict[str, Any]:
    exp = fixture["expected"]
    lo, hi = exp["overall"]
    scores = dimension_scores(report, fixture["track"])
    names = [r.split(":", 1)[0] for r in RUBRICS[fixture["track"]]]
    dim_out = []
    for name in names:
        score = scores.get(name)
        band = exp.get("dimensions", {}).get(name)
        cap = exp.get("max_dimension")
        if score is None:
            dim_out.append(f"{name} missing")
        elif band and not band[0] <= score <= band[1]:
            dim_out.append(f"{name} {score} not in {band[0]}-{band[1]}")
        elif cap is not None and score > cap:
            dim_out.append(f"{name} {score} above {cap}")
    return {
        "overall": report.overall_score,
        "in_band": lo <= report.overall_score <= hi,
        "dims": [scores.get(n) for n in names],
        "dim_out": dim_out,
        "quotes": len(report.notable_moments),
        "bad_quotes": quote_problems(report, fixture["transcript"]),
    }


async def run(setups: list[Setup], fixtures: list[dict[str, Any]], out: Path) -> None:
    from google import genai

    settings = get_settings()
    client = BudgetedClient(genai.Client(api_key=settings.gemini_api_key))
    summaries = {f["name"]: (await final_run_summary(f))[0] for f in fixtures}
    bank = get_bank()

    planned: dict[str, int] = dict.fromkeys(CAPS, 0)
    for s in setups:
        n = s.runs * len(fixtures)
        planned[s.grade_model] += n
        if s.extract_model:
            planned[s.extract_model] += n
    print("planned calls (before retries):", planned, "caps:", CAPS)
    for model, n in planned.items():
        if n > CAPS[model]:
            raise SystemExit(f"{model}: {n} planned calls exceed the cap of {CAPS[model]}; no calls made")

    async def one(setup: Setup, fixture: dict[str, Any], run_no: int) -> None:
        calls: list[tuple[str, float]] = []
        _report_calls.set(calls)
        problem = bank.get(fixture["problem_id"])
        assert problem is not None
        started = time.monotonic()
        record: dict[str, Any] = {"setup": setup.key, "case": fixture["name"], "run": run_no}
        try:
            report = await setup.generator(client).generate(
                track_id=fixture["track"],
                problem_text=problem.prompt_text(),
                transcript=fixture["transcript"],
                code=fixture["code"],
                test_summary=summaries[fixture["name"]],
            )
            record.update(score_report(fixture, report), report=report.model_dump())
        except Exception as exc:  # noqa: BLE001
            record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        record["api_seconds"] = round(sum(d for _, d in calls), 2)
        record["wall_seconds"] = round(time.monotonic() - started, 2)
        record["calls"] = [m for m, _ in calls]
        with out.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        status = record.get("error") or f"overall {record['overall']}"
        print(
            f"  {setup.key} {fixture['name']} run {run_no}: {status} ({record['api_seconds']}s)",
            file=sys.stderr,
        )

    # Interleave setups so a stop leaves a comparable partial picture.
    jobs = [
        one(s, f, r)
        for r in range(1, max(s.runs for s in setups) + 1)
        for f in fixtures
        for s in setups
        if r <= s.runs
    ]
    await asyncio.gather(*jobs)
    print("calls used:", client.used, "| stopped:", client.stopped or "no")


def summarize(path: Path, fixtures: list[dict[str, Any]]) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    bands = {f["name"]: f["expected"]["overall"] for f in fixtures}
    order = [f["name"] for f in fixtures]
    for key in sorted({r["setup"] for r in rows}):
        setup = SETUPS[key]
        mine = [r for r in rows if r["setup"] == key]
        ok = [r for r in mine if "error" not in r]
        print(f"\n== {key}: {setup.label} ({len(ok)} reports, {len(mine) - len(ok)} errors)")
        print(
            f"{'case':<17} {'band':>5}  {'overall':<8} {'spread':>6}  {'dim out':>7}  {'bad q':>5}  dims per run"
        )
        means: dict[str, float] = {}
        for name in order:
            runs = [r for r in ok if r["case"] == name]
            if not runs:
                continue
            overall = [r["overall"] for r in runs]
            means[name] = statistics.mean(overall)
            lo, hi = bands[name]
            flag = "" if all(r["in_band"] for r in runs) else "  OUT"
            dims = " | ".join(" ".join(str(d) for d in r["dims"]) for r in runs)
            print(
                f"{name:<17} {lo}-{hi:<3}  {','.join(map(str, overall)):<8} {max(overall) - min(overall):>6}  "
                f"{sum(len(r['dim_out']) for r in runs):>7}  {sum(len(r['bad_quotes']) for r in runs):>5}  {dims}{flag}"
            )
        for track in ("swe", "debug"):
            s, m, p = (means.get(f"{track}-{lvl}") for lvl in ("strong", "mediocre", "poor"))
            if None not in (s, m, p):
                print(f"order {track}: strong {s:.2f} > mediocre {m:.2f} > poor {p:.2f}: {s > m > p}")
        if ok:
            in_band = sum(r["in_band"] for r in ok)
            quotes = sum(r["quotes"] for r in ok)
            bad = sum(len(r["bad_quotes"]) for r in ok)
            print(
                f"in band {in_band}/{len(ok)}; dimension outliers {sum(len(r['dim_out']) for r in ok)}; "
                f"quotes valid {quotes - bad}/{quotes}; latency mean {statistics.mean(r['api_seconds'] for r in ok):.1f}s "
                f"(max {max(r['api_seconds'] for r in ok):.1f}s); calls per report {statistics.mean(len(r['calls']) for r in ok):.2f}"
            )
            for r in ok:
                for msg in r["dim_out"] + r["bad_quotes"]:
                    print(f"    {r['case']} run {r['run']}: {msg}")
        for r in mine:
            if "error" in r:
                print(f"    {r['case']} run {r['run']}: ERROR {r['error'][:160]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--setup", action="append", choices=sorted(SETUPS), help="setups to run (default all)"
    )
    parser.add_argument("--case", action="append", help="only these cases (repeatable)")
    parser.add_argument("--runs", type=int, help="override runs per case for every chosen setup")
    parser.add_argument(
        "--summarize", type=Path, help="print the tables for an existing results file; no calls"
    )
    args = parser.parse_args()
    fixtures = load_fixtures(args.case)
    if args.summarize:
        summarize(args.summarize, load_fixtures(None))
        return 0
    if not get_settings().gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set (backend/.env)")
    setups = [SETUPS[k] for k in (args.setup or sorted(SETUPS))]
    if args.runs:
        setups = [Setup(s.key, s.label, args.runs, s.grade_model, s.extract_model) for s in setups]
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"compare-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    print(f"results: {out}")
    asyncio.run(run(setups, fixtures, out))
    summarize(out, load_fixtures(None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
