"""Run a candidate's Python module against a problem's unittest file in a child process.

This is a *practice* sandbox, not a security boundary: a separate process with an isolated
interpreter (-I), an empty environment, a throwaway working directory, a wall-clock timeout and
rlimits on CPU, memory, file size and open files. It stops runaway loops and accidental damage. It
does not stop a determined attacker from reading the filesystem or the network. On a public
deployment run the backend in a locked-down container (or swap this for Piston) and keep
CODE_EXECUTION_ENABLED off otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

HARNESS = Path(__file__).with_name("_harness.py")
MAX_OUTPUT_CHARS = 8000
# Bound concurrent child processes across all sessions on this server.
_SLOTS = asyncio.Semaphore(4)

Status = Literal["passed", "failed", "error", "skipped"]


@dataclass(slots=True)
class TestOutcome:
    name: str
    status: Status
    message: str = ""


@dataclass(slots=True)
class RunResult:
    passed: int
    total: int
    outcomes: list[TestOutcome] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    load_error: str | None = None  # the module or tests failed to import (syntax error, etc.)
    timed_out: bool = False
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total and not self.load_error and not self.timed_out

    def public(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d

    def summary(self, *, max_failures: int = 4) -> str:
        """One plain-text paragraph for the interviewer model and the grader."""
        if self.timed_out:
            return "The run timed out (likely an infinite loop or very slow code)."
        if self.load_error:
            return f"The code failed to load, so no tests ran: {self.load_error}"
        lines = [f"{self.passed} of {self.total} tests passed."]
        bad = [o for o in self.outcomes if o.status in ("failed", "error")]
        for o in bad[:max_failures]:
            lines.append(f"- {o.name} {o.status}: {o.message}")
        if len(bad) > max_failures:
            lines.append(f"- and {len(bad) - max_failures} more failing.")
        if self.stdout.strip():
            lines.append(f"Printed output (truncated): {self.stdout.strip()[:500]}")
        return "\n".join(lines)


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… ({len(text) - MAX_OUTPUT_CHARS} more characters truncated)"


def _limits(cpu_seconds: int, memory_mb: int) -> None:  # pragma: no cover - runs in the child
    import resource

    def _set(which: int, value: int) -> None:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(which, (value, value))

    _set(resource.RLIMIT_CPU, cpu_seconds)
    _set(resource.RLIMIT_FSIZE, 2 * 1024 * 1024)
    _set(resource.RLIMIT_NOFILE, 64)
    _set(resource.RLIMIT_CORE, 0)
    if sys.platform != "darwin":  # macOS does not enforce RLIMIT_AS and may reject it
        _set(resource.RLIMIT_AS, memory_mb * 1024 * 1024)


def _protect_parent_environment() -> None:
    """Linux: stop the child reading this process's secrets through /proc/<ppid>/environ or mem.

    The child gets an empty environment, but a same-user process can read the parent's /proc
    files. On Vercel the parent holds GEMINI_API_KEY and DATABASE_URL. A non-dumpable process has
    root-owned /proc files, so the child cannot open them. The child itself is dumpable again
    after exec, so this does not affect it.
    """
    if sys.platform != "linux":
        return
    with contextlib.suppress(Exception):
        import ctypes

        pr_set_dumpable = 4
        ctypes.CDLL(None, use_errno=True).prctl(pr_set_dumpable, 0, 0, 0, 0)


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


async def run_python_tests(
    code: str,
    *,
    module_name: str,
    test_code: str,
    time_limit: float = 6.0,
    memory_mb: int = 512,
) -> RunResult:
    """Write `code` as <module_name>.py next to test_<module_name>.py and run the tests."""
    if not module_name.isidentifier():
        raise ValueError(f"bad module name {module_name!r}")
    test_module = f"test_{module_name}"
    _protect_parent_environment()
    async with _SLOTS:
        with tempfile.TemporaryDirectory(prefix="codeverse-run-") as tmp:
            work = Path(tmp)
            (work / f"{module_name}.py").write_text(code, encoding="utf-8")
            (work / f"{test_module}.py").write_text(test_code, encoding="utf-8")
            results_path = work / ".results.json"
            started = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-B",
                str(HARNESS),
                str(work),
                test_module,
                str(results_path),
                cwd=work,
                env={"PYTHONIOENCODING": "utf-8", "HOME": str(work)},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # own process group, so a timeout kills any children too
                preexec_fn=lambda: _limits(int(time_limit) + 1, memory_mb),
            )
            timed_out = False
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=time_limit)
            except TimeoutError:
                timed_out = True
                _kill_group(proc.pid)
                out, err = await proc.communicate()
            finally:
                # Cancelled (session closed mid-run) or anything else: never leave the child behind.
                if proc.returncode is None:
                    _kill_group(proc.pid)
            duration_ms = round((time.monotonic() - started) * 1000)

            data: dict = {}
            if not timed_out and results_path.is_file():
                with contextlib.suppress(ValueError, OSError):
                    data = json.loads(results_path.read_text(encoding="utf-8"))

    def clean(text: str) -> str:
        # Hide server temp paths: "/tmp/codeverse-run-x/cart.py" -> "cart.py".
        for prefix in (str(work) + os.sep, str(work.resolve()) + os.sep):
            text = text.replace(prefix, "")
        return text

    return build_result(
        clean(out.decode("utf-8", "replace")),
        clean(err.decode("utf-8", "replace")),
        data,
        timed_out=timed_out,
        returncode=proc.returncode,
        duration_ms=duration_ms,
        clean=clean,
    )


def build_result(
    stdout: str,
    stderr: str,
    data: dict,
    *,
    timed_out: bool,
    returncode: int | None,
    duration_ms: int,
    clean: Callable[[str], str] = lambda t: t,
) -> RunResult:
    """Turn the harness's results file (`data`) and the process output into a RunResult."""
    outcomes = [TestOutcome(**o) for o in data.get("outcomes", [])]
    load_error = clean(data["load_error"]) if data.get("load_error") else None
    if not timed_out and not data:
        # The child died before writing results (killed by an rlimit, os._exit, a crash).
        load_error = f"The test process exited with code {returncode} before reporting results."
    return RunResult(
        passed=sum(o.status == "passed" for o in outcomes),
        total=len(outcomes),
        outcomes=outcomes,
        stdout=_truncate(stdout),
        stderr=_truncate(stderr),
        load_error=load_error,
        timed_out=timed_out,
        duration_ms=duration_ms,
    )
