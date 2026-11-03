"""POST /api/run_tests: run the hidden unittest suite on the candidate's code (debugging track)."""

import sys
from pathlib import Path

# The shared code lives in backend/codeverse (vercel.json includes it in the bundle).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from codeverse.web import service
from codeverse.web.handler import JsonHandler


class handler(JsonHandler):  # noqa: N801  (Vercel looks for this name)
    POST = staticmethod(service.run_tests)
