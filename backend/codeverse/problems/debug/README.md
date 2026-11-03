# Debugging-track problems

Each directory is one problem. The directory name is the problem id.

| File | Who sees it | What it is |
| --- | --- | --- |
| `problem.json` | candidate: title, statement (the bug report), constraints, tags. Interviewer only: `bugs`, `hints` | metadata; `module_name` is the file name the tests import |
| `buggy.py` | candidate (preloaded in the editor), interviewer | the module with planted bugs |
| `fixed.py` | nobody at runtime | reference fix; CI proves the tests pass on it |
| `test_<module_name>.py` | nobody (source); candidate sees test names and failure messages | stdlib `unittest` suite run by **Run tests** and again on the final code for the report |

Rules, enforced by `tests/test_runner.py` and `tests/test_problems.py`:

- `buggy.py` must fail at least one test and `fixed.py` must pass all of them.
- Every planted bug needs a test that fails because of that bug. Check this by hand: fix all but
  one bug and confirm the suite still fails.
- Standard library only. The runner has no network and an empty environment.
- Test names and assertion messages are shown to the candidate, so describe the symptom
  ("bob's new cart already contains alice's items"), never the fix.
- `bugs` are written for the interviewer and the grader: say where the bug is, why it produces
  the reported symptom, and what a root-cause fix looks like.
- Code here is deliberately wrong, so ruff skips this directory.
