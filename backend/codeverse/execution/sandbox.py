"""Run a TestJob in a fresh Vercel Sandbox (Firecracker microVM): one sandbox per run.

Candidate code never runs in the function process, so it cannot read the project's secrets
(GEMINI_API_KEY, DATABASE_URL) from the environment or /proc. The sandbox gets no environment
variables and a deny-all network policy. The function only uploads the code, the tests and the
harness, and reads back the results file.

Authentication: the `vercel` SDK uses the request's OIDC token on Vercel (see
web/handler.py, which registers the request headers) or VERCEL_OIDC_TOKEN locally.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from typing import Any

from .jobs import TestJob
from .runner import HARNESS, RunResult, build_result

WORKDIR = "codeverse-run"
RESULTS = ".results.json"
TIMEOUT_EXIT = 124  # coreutils `timeout` exit status when the limit is hit
# Time for the sandbox to boot, upload files and tear down, on top of the job's own limit.
SESSION_OVERHEAD_SECONDS = 60


def _default_create(**kwargs: Any) -> Any:
    from vercel import sandbox

    return sandbox.create_sandbox(**kwargs)


class SandboxRunner:
    def __init__(self, *, vcpus: int = 1, create: Callable[..., Any] | None = None) -> None:
        self._vcpus = vcpus
        self._create = create or _default_create

    async def run(self, job: TestJob) -> RunResult:
        from vercel.sandbox import NetworkPolicy, SandboxResources

        started = time.monotonic()
        limit = max(1, round(job.time_limit))
        async with self._create(
            network_policy=NetworkPolicy.deny_all(),
            execution_time_limit=limit + SESSION_OVERHEAD_SECONDS,
            resources=SandboxResources(vcpus=self._vcpus),
            persistent=False,
            tags={"app": "codeverse", "purpose": "run-tests"},
        ) as box:
            await box.fs.mkdir(WORKDIR)
            async with box.fs.batch(cwd=WORKDIR) as batch:
                batch.write_text(f"{job.module_name}.py", job.code)
                batch.write_text(f"{job.test_module}.py", job.test_code)
                batch.write_text("_harness.py", HARNESS.read_text(encoding="utf-8"))
            proc = await box.run_process(
                "timeout",
                ["-k", "1", str(limit), "python3", "-I", "-B", "_harness.py", ".", job.test_module, RESULTS],
                cwd=WORKDIR,
                env={"PYTHONIOENCODING": "utf-8"},
                kill_after=limit + 5,
                capture_output=True,
            )
            timed_out = proc.returncode == TIMEOUT_EXIT
            data: dict = {}
            if not timed_out:
                with contextlib.suppress(Exception):
                    data = json.loads(await box.fs.read_text(f"{WORKDIR}/{RESULTS}"))
        return build_result(
            proc.stdout or "",
            proc.stderr or "",
            data,
            timed_out=timed_out,
            returncode=proc.returncode,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
