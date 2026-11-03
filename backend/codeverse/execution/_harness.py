"""Runs inside the child process. Not imported by the server.

usage: python -I _harness.py <workdir> <test_module> <results_path>

Imports the test module from workdir, runs it with unittest, and writes a JSON summary to
results_path. Only test names and failure messages are reported, never test source, because the
test file is hidden from the candidate.
"""

import json
import sys
import traceback
import unittest


def _message(err) -> str:
    exc_type, exc, tb = err
    # The last frame that is not the test file itself points at the candidate's code.
    frames = traceback.extract_tb(tb)
    where = ""
    for fr in reversed(frames):
        if not fr.filename.endswith(f"{sys.argv[2]}.py") and "unittest" not in fr.filename:
            where = f" (at {fr.filename.rsplit('/', 1)[-1]}:{fr.lineno} in {fr.name})"
            break
    text = "".join(traceback.format_exception_only(exc_type, exc)).strip()
    return (text + where)[:600]


class _Result(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.outcomes: list[dict] = []

    def _name(self, test) -> str:
        return test.id().split(".", 1)[-1]

    def addSuccess(self, test) -> None:
        self.outcomes.append({"name": self._name(test), "status": "passed", "message": ""})

    def addFailure(self, test, err) -> None:
        self.outcomes.append({"name": self._name(test), "status": "failed", "message": _message(err)})

    def addError(self, test, err) -> None:
        self.outcomes.append({"name": self._name(test), "status": "error", "message": _message(err)})

    def addSkip(self, test, reason) -> None:
        self.outcomes.append({"name": self._name(test), "status": "skipped", "message": str(reason)})


def main() -> None:
    workdir, test_module, results_path = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.path.insert(0, workdir)
    summary: dict = {"outcomes": [], "load_error": None}
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(test_module)
    except Exception:
        exc_type, exc, _ = sys.exc_info()
        summary["load_error"] = "".join(traceback.format_exception_only(exc_type, exc)).strip()[:1500]
    else:
        result = _Result()
        suite.run(result)
        summary["outcomes"] = result.outcomes
    # Tests may have redirected stdout; write results to a file instead.
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f)


if __name__ == "__main__":
    main()
