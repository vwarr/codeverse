"""The code runner, and the invariant every debug problem must satisfy:
its buggy module fails the suite and its reference fix passes all of it."""

import sys
import unittest

from codeverse.execution import run_python_tests
from codeverse.problems.bank import load_bank

TESTS = """
import unittest
from mod import add

class AddTests(unittest.TestCase):
    def test_small(self):
        self.assertEqual(add(1, 2), 3)

    def test_negative(self):
        self.assertEqual(add(-1, -1), -2)
"""

SECRET_MARKER = "very-secret-test-source"


def _read_pid(path: str) -> int | None:
    try:
        with open(path) as f:
            text = f.read().strip()
    except FileNotFoundError:
        return None
    return int(text) if text else None


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child we haven't reaped yet is a zombie; treat it as gone.
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True  # not our child to reap, and it still exists
    return waited == 0


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def run_mod(self, code: str, tests: str = TESTS, **kw):
        return await run_python_tests(code, module_name="mod", test_code=tests, **kw)

    async def test_all_pass(self) -> None:
        r = await self.run_mod("def add(a, b):\n    return a + b\n")
        self.assertTrue(r.ok)
        self.assertEqual((r.passed, r.total), (2, 2))
        self.assertEqual({o.name for o in r.outcomes}, {"AddTests.test_small", "AddTests.test_negative"})

    async def test_failures_are_reported_with_messages(self) -> None:
        r = await self.run_mod("def add(a, b):\n    return a - b\n")
        self.assertFalse(r.ok)
        self.assertEqual((r.passed, r.total), (0, 2))
        failed = {o.name: o for o in r.outcomes}
        self.assertEqual(failed["AddTests.test_small"].status, "failed")
        self.assertIn("-1 != 3", failed["AddTests.test_small"].message)
        self.assertIn("0 of 2 tests passed", r.summary())

    async def test_exception_in_candidate_code_points_at_their_line(self) -> None:
        r = await self.run_mod("def add(a, b):\n    return a + b + undefined_name\n")
        self.assertTrue(all(o.status == "error" for o in r.outcomes))
        self.assertIn("NameError", r.outcomes[0].message)
        self.assertIn("mod.py:2", r.outcomes[0].message)

    async def test_syntax_error_is_a_load_error_without_server_paths(self) -> None:
        r = await self.run_mod("def add(a, b) return a\n")
        self.assertFalse(r.ok)
        self.assertEqual(r.total, 0)
        assert r.load_error is not None
        self.assertIn("SyntaxError", r.load_error)
        self.assertIn("mod.py", r.load_error)
        self.assertNotIn("codeverse-run-", r.load_error)
        self.assertIn("failed to load", r.summary())

    async def test_infinite_loop_times_out(self) -> None:
        r = await self.run_mod("def add(a, b):\n    while True:\n        pass\n", time_limit=1.0)
        self.assertTrue(r.timed_out)
        self.assertFalse(r.ok)
        self.assertLess(r.duration_ms, 5000)
        self.assertIn("timed out", r.summary())

    async def test_stdout_is_captured_and_truncated(self) -> None:
        r = await self.run_mod("print('x' * 20000)\ndef add(a, b):\n    return a + b\n")
        self.assertTrue(r.ok)
        self.assertIn("truncated", r.stdout)
        self.assertLess(len(r.stdout), 9000)

    async def test_process_exit_is_reported(self) -> None:
        r = await self.run_mod("import os\nos._exit(3)\n")
        self.assertFalse(r.ok)
        assert r.load_error is not None
        self.assertIn("code 3", r.load_error)

    async def test_environment_is_empty(self) -> None:
        tests = (
            "import os, unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_env(self):\n"
            "        self.assertNotIn('GEMINI_API_KEY', os.environ)\n"
        )
        import os

        os.environ["GEMINI_API_KEY"] = "should-not-leak"
        try:
            r = await self.run_mod("", tests)
        finally:
            del os.environ["GEMINI_API_KEY"]
        self.assertTrue(r.ok, r.summary())

    async def test_test_source_is_not_echoed(self) -> None:
        tests = TESTS.replace("def test_small(self):", f"def test_small(self):\n        '{SECRET_MARKER}'")
        r = await self.run_mod("def add(a, b):\n    return 0\n", tests)
        blob = repr(r.public())
        self.assertNotIn(SECRET_MARKER, blob)

    async def test_cancelling_a_run_kills_the_child(self) -> None:
        import asyncio
        import os
        import tempfile

        pid_file = os.path.join(tempfile.mkdtemp(), "pid")
        code = f"import os, time\nopen({pid_file!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
        task = asyncio.create_task(self.run_mod(code, time_limit=30))
        pid = None
        for _ in range(200):
            await asyncio.sleep(0.02)
            pid = _read_pid(pid_file)
            if pid:
                break
        self.assertIsNotNone(pid, "child never started")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        assert pid is not None
        for _ in range(50):
            if not _alive(pid):
                return
            await asyncio.sleep(0.05)
        self.fail(f"child {pid} still running after cancel")

    async def test_bad_module_name_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await run_python_tests("", module_name="../evil", test_code="")


class DebugProblemInvariantTests(unittest.IsolatedAsyncioTestCase):
    async def test_buggy_fails_and_reference_passes(self) -> None:
        problems = load_bank().list(track="debug")
        self.assertGreaterEqual(len(problems), 3)
        for p in problems:
            assert p.module_name and p.test_code and p.reference_solution
            with self.subTest(problem=p.id, version="buggy"):
                r = await run_python_tests(
                    p.starter_code["python"], module_name=p.module_name, test_code=p.test_code
                )
                self.assertIsNone(r.load_error, p.id)
                self.assertGreater(r.total, 0, p.id)
                self.assertLess(r.passed, r.total, f"{p.id}: buggy code passes every test")
            with self.subTest(problem=p.id, version="reference"):
                r = await run_python_tests(
                    p.reference_solution, module_name=p.module_name, test_code=p.test_code
                )
                self.assertTrue(r.ok, f"{p.id}: reference fix fails\n{r.summary(max_failures=20)}")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(sys.platform == "linux", "the /proc protection is Linux-only")
class ParentEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_cannot_read_parent_environ(self) -> None:
        code = (
            "import os\n"
            "def add(a, b):\n"
            "    try:\n"
            "        open(f'/proc/{os.getppid()}/environ', 'rb').read()\n"
            "        return 'leaked'\n"
            "    except OSError:\n"
            "        return a + b\n"
        )
        r = await run_python_tests(code, module_name="mod", test_code=TESTS)
        self.assertTrue(r.ok, r.summary())
