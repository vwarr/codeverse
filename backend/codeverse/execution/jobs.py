"""What to run, and where. One interface for every track that runs candidate code.

A `TestJob` is self-contained: the candidate's module, a stdlib `unittest` file that imports it,
and a time limit. A `CodeRunner` runs a job somewhere and returns a `RunResult`:

- `SandboxRunner` (execution/sandbox.py): a fresh Vercel Sandbox microVM per run, no network, no
  secrets. Use this on Vercel.
- `LocalRunner`: a child process on this machine (runner.py). For local development and tests only:
  the child can read files and make network calls as this process's user.

`job_for(problem, code)` builds the job for a problem:
- debugging track: the problem's hidden `test_code` against `<module_name>.py`;
- software-engineering track: a suite generated from the bank's `tests` (args/expected) that calls
  `function_name` from `solution.py`. Python only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .runner import RunResult, run_python_tests

if TYPE_CHECKING:
    from ..problems.bank import Problem

SWE_MODULE = "solution"


@dataclass(frozen=True, slots=True)
class TestJob:
    __test__ = False  # not a pytest test class

    code: str  # the candidate's source, saved as <module_name>.py
    module_name: str
    test_code: str  # unittest source; imports from module_name; saved as test_<module_name>.py
    time_limit: float = 6.0

    @property
    def test_module(self) -> str:
        return f"test_{self.module_name}"


class CodeRunner(Protocol):
    async def run(self, job: TestJob) -> RunResult: ...


class LocalRunner:
    """Child process on this machine. Never use it in a process that holds secrets."""

    async def run(self, job: TestJob) -> RunResult:
        return await run_python_tests(
            job.code, module_name=job.module_name, test_code=job.test_code, time_limit=job.time_limit
        )


_SWE_TEMPLATE = """import copy
import json
import unittest

from {module} import {function}

CASES = json.loads({cases!r})
# True when the problem accepts the items of the returned list in any order (bank.json "compare").
ANY_ORDER = {any_order!r}


def _plain(value):
    # Tuples compare equal to the JSON lists in `expected`.
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _sorted(value):
    try:
        return sorted(value)
    except TypeError:
        return value


class SolutionTests(unittest.TestCase):
    pass


def _make(case):
    def test(self):
        args = copy.deepcopy(case["args"])
        got, expected = _plain({function}(*args)), case["expected"]
        if ANY_ORDER and isinstance(got, list) and isinstance(expected, list):
            got, expected = _sorted(got), _sorted(expected)
        self.assertEqual(got, expected)

    return test


for _i, _case in enumerate(CASES, 1):
    setattr(SolutionTests, f"test_case_{{_i}}", _make(_case))
"""


def swe_test_code(function_name: str, cases: list[dict], *, any_order: bool = False) -> str:
    if not function_name.isidentifier():
        raise ValueError(f"bad function name {function_name!r}")
    return _SWE_TEMPLATE.format(
        module=SWE_MODULE, function=function_name, cases=json.dumps(cases), any_order=any_order
    )


def job_for(problem: Problem, code: str, *, time_limit: float = 6.0) -> TestJob | None:
    """The test job for a problem, or None when the problem has no runnable tests."""
    if problem.track == "debug" and problem.module_name and problem.test_code:
        return TestJob(code, problem.module_name, problem.test_code, time_limit)
    if problem.track == "swe" and problem.function_name and problem.tests:
        cases = [t.model_dump() for t in problem.tests]
        test_code = swe_test_code(problem.function_name, cases, any_order=problem.compare == "any_order")
        return TestJob(code, SWE_MODULE, test_code, time_limit)
    return None
