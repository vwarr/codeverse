"""The runner interface: jobs for each track, and the Vercel Sandbox runner with a fake sandbox."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from codeverse.execution import LocalRunner, SandboxRunner, TestJob, job_for
from codeverse.problems.bank import get_bank

TWO_SUM = (
    "def two_sum(nums, target):\n"
    "    seen = {}\n"
    "    for i, n in enumerate(nums):\n"
    "        if target - n in seen:\n"
    "            return [seen[target - n], i]\n"
    "        seen[n] = i\n"
)


def test_job_for_each_track() -> None:
    bank = get_bank()
    debug = bank.list(track="debug")[0]
    job = job_for(debug, "code", time_limit=3)
    assert job is not None and job.module_name == debug.module_name and job.test_code == debug.test_code
    assert job.time_limit == 3 and job.test_module == f"test_{debug.module_name}"

    swe = bank.get("two-sum")
    assert swe is not None
    job = job_for(swe, TWO_SUM)
    assert job is not None and job.module_name == "solution"
    no_tests = next(p for p in bank.list(track="swe") if not p.tests)
    assert job_for(no_tests, "x") is None


def test_generated_swe_suite_runs_locally() -> None:
    swe = get_bank().get("two-sum")
    assert swe is not None
    good = asyncio.run(LocalRunner().run(job_for(swe, TWO_SUM)))  # type: ignore[arg-type]
    assert good.ok and good.total == len(swe.tests)
    bad = asyncio.run(LocalRunner().run(job_for(swe, "def two_sum(nums, target):\n    return [0, 0]\n")))  # type: ignore[arg-type]
    assert not bad.ok and bad.passed < bad.total


def test_swe_any_order_flag() -> None:
    bank = get_bank()
    two_sum = bank.get("two-sum")
    merge = bank.get("merge-sorted-arrays")
    assert two_sum is not None and merge is not None
    assert two_sum.compare == "any_order" and merge.compare == "exact"
    # two-sum accepts the indices in any order, and a tuple is the same as a list.
    reversed_pair = (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        if target - n in seen:\n"
        "            return (i, seen[target - n])\n"
        "        seen[n] = i\n"
    )
    run = asyncio.run(LocalRunner().run(job_for(two_sum, reversed_pair)))  # type: ignore[arg-type]
    assert run.ok, run.summary()
    # merge-sorted-arrays compares exactly: the right items in the wrong order fail.
    unsorted = "def merge(nums1, nums2):\n    return nums2 + nums1\n"
    run = asyncio.run(LocalRunner().run(job_for(merge, unsorted)))  # type: ignore[arg-type]
    assert not run.ok
    good = "def merge(nums1, nums2):\n    return sorted(nums1 + nums2)\n"
    assert asyncio.run(LocalRunner().run(job_for(merge, good))).ok  # type: ignore[arg-type]


def test_any_order_accepts_a_tuple_in_the_other_order() -> None:
    from codeverse.execution import TestJob
    from codeverse.execution.jobs import swe_test_code

    suite = swe_test_code("pair", [{"args": [], "expected": [1, 0]}], any_order=True)
    code = "def pair():\n    return (0, 1)\n"
    assert asyncio.run(LocalRunner().run(TestJob(code, "solution", suite))).ok
    exact = swe_test_code("pair", [{"args": [], "expected": [1, 0]}])
    assert not asyncio.run(LocalRunner().run(TestJob(code, "solution", exact))).ok


def test_swe_suite_hides_the_cases() -> None:
    two_sum = get_bank().get("two-sum")
    assert two_sum is not None
    public = two_sum.public()
    assert "tests" not in public and "compare" not in public
    assert public["has_tests"] is True
    run = asyncio.run(LocalRunner().run(job_for(two_sum, "def two_sum(nums, target):\n    return None\n")))  # type: ignore[arg-type]
    # Test names are numbered; they say nothing about the inputs.
    assert [o.name for o in run.outcomes] == [f"SolutionTests.test_case_{i}" for i in range(1, 4)]


class FakeBox:
    def __init__(self, returncode: int, results: dict | None) -> None:
        self.files: dict[str, str] = {}
        self.dirs: list[str] = []
        self.commands: list[dict[str, Any]] = []
        self.returncode, self.results = returncode, results
        box = self

        class Batch:
            def __init__(self, cwd: str) -> None:
                self.cwd = cwd

            async def __aenter__(self) -> Batch:
                return self

            async def __aexit__(self, *_: Any) -> None:
                return None

            def write_text(self, path: str, text: str) -> None:
                box.files[f"{self.cwd}/{path}"] = text

        async def mkdir(path: str) -> None:
            self.dirs.append(path)

        async def read_text(path: str) -> str:
            if self.results is None:
                raise FileNotFoundError(path)
            return json.dumps(self.results)

        self.fs = SimpleNamespace(mkdir=mkdir, batch=lambda cwd: Batch(cwd), read_text=read_text)

    async def run_process(self, command: str, args: list[str], **kw: Any) -> Any:
        self.commands.append({"command": command, "args": args, **kw})
        return SimpleNamespace(returncode=self.returncode, stdout="out", stderr="")


class FakeCreate:
    def __init__(self, box: FakeBox) -> None:
        self.box, self.kwargs, self.exited = box, {}, False

    def __call__(self, **kwargs: Any) -> FakeCreate:
        self.kwargs = kwargs
        return self

    async def __aenter__(self) -> FakeBox:
        return self.box

    async def __aexit__(self, *_: Any) -> None:
        self.exited = True


JOB = TestJob("def f(): ...", "mod", "import unittest", time_limit=4)


def test_sandbox_runner_isolates_the_run() -> None:
    from vercel.sandbox import NetworkPolicy

    results = {"outcomes": [{"name": "T.test_a", "status": "passed", "message": ""}], "load_error": None}
    create = FakeCreate(FakeBox(0, results))
    result = asyncio.run(SandboxRunner(create=create).run(JOB))
    assert result.ok and result.passed == 1 and result.stdout == "out"

    kw = create.kwargs
    assert kw["network_policy"] == NetworkPolicy.deny_all()
    assert "env" not in kw  # no secrets go into the sandbox
    assert kw["persistent"] is False and kw["execution_time_limit"] <= 4 + 60
    assert create.exited  # the context manager stops and destroys the sandbox

    box = create.box
    assert set(box.files) == {
        "codeverse-run/mod.py",
        "codeverse-run/test_mod.py",
        "codeverse-run/_harness.py",
    }
    (cmd,) = box.commands
    assert cmd["command"] == "timeout" and cmd["args"][:3] == ["-k", "1", "4"]
    assert cmd["env"] == {"PYTHONIOENCODING": "utf-8"}


def test_sandbox_runner_reports_timeouts_and_crashes() -> None:
    timed_out = asyncio.run(SandboxRunner(create=FakeCreate(FakeBox(124, None))).run(JOB))
    assert timed_out.timed_out and not timed_out.ok
    crashed = asyncio.run(SandboxRunner(create=FakeCreate(FakeBox(137, None))).run(JOB))
    assert not crashed.timed_out and "exited with code 137" in (crashed.load_error or "")
