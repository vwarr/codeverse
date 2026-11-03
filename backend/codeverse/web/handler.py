"""`BaseHTTPRequestHandler` adapter: each /api/*.py file subclasses `JsonHandler` and names its routes."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlsplit

from .service import ApiError, Deps, Request, default_deps

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000
Route = Callable[[Request, Deps], Any]


# Client-address headers, most trusted first (https://vercel.com/docs/headers/request-headers).
# Vercel's edge sets all three to the visitor's public IP. The docs say it overwrites a client's
# x-forwarded-for; they call the other two "identical" but do not state the overwrite for them.
# x-vercel-forwarded-for comes first: the docs say x-forwarded-for "could be overwritten if you're
# using a proxy on top of Vercel", and varunwarrier.com/codeverse reaches this project through a
# rewrite on another Vercel project. x-forwarded-for is last and only its first entry is used; it is
# the one header a non-Vercel host (local `vercel dev`, a plain proxy) may pass through from clients.
_IP_HEADERS = ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for")


def client_ip(headers: Any, fallback: str) -> str:
    for name in _IP_HEADERS:
        value = (headers.get(name) or "").split(",")[0].strip()
        if value:
            return value
    return fallback


def dispatch(route: Route | None, request: Request, deps: Deps) -> tuple[int, Any]:
    """Run a route and map the outcome to (status, JSON body). Testable without a socket."""
    if route is None:
        return 405, {"ok": False, "error": "method not allowed"}
    try:
        result = route(request, deps)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        return 200, result
    except ApiError as exc:
        return exc.status, {"ok": False, "error": exc.message}
    except Exception:  # noqa: BLE001
        log.exception("unhandled error")
        return 500, {"ok": False, "error": "internal error"}


def _register_vercel_headers(headers: Any) -> None:
    """Let the `vercel` SDK find this request's OIDC token (used by the Sandbox runner)."""
    try:
        from vercel.headers import set_headers
    except ImportError:  # pragma: no cover
        return
    set_headers({k.lower(): v for k, v in headers.items()})


class JsonHandler(BaseHTTPRequestHandler):
    GET: ClassVar[Route | None] = None
    POST: ClassVar[Route | None] = None
    deps: ClassVar[Callable[[], Deps]] = staticmethod(default_deps)

    def do_GET(self) -> None:  # noqa: N802
        self._handle(type(self).GET, {})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        if length > MAX_BODY_BYTES:
            self._send(413, {"ok": False, "error": "request too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"ok": False, "error": "invalid JSON"})
            return
        if not isinstance(body, dict):
            self._send(400, {"ok": False, "error": "expected a JSON object"})
            return
        self._handle(type(self).POST, body)

    def _handle(self, route: Route | None, body: dict[str, Any]) -> None:
        query = dict(parse_qsl(urlsplit(self.path).query))
        _register_vercel_headers(self.headers)
        request = Request(
            query=query,
            body=body,
            ip=client_ip(self.headers, self.client_address[0]),
            headers={"x-client-id": self.headers.get("x-client-id") or ""},
        )
        status, payload = dispatch(route, request, type(self).deps())
        self._send(status, payload)

    def _send(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
