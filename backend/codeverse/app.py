"""ASGI application factory: FastAPI for REST, python-socketio for the interview channel."""

from __future__ import annotations

import logging

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .interview.feedback import FeedbackGenerator, GeminiFeedbackGenerator, StaticFeedbackGenerator
from .problems.api import router as api_router
from .problems.bank import get_bank
from .sockets import register_handlers
from .voice.base import VoiceBackend

log = logging.getLogger(__name__)


def _gemini_client(settings: Settings):
    from google import genai

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=settings.gemini_api_key)


def make_backend_factory(settings: Settings):
    if settings.voice_backend == "fake":
        from .voice.fake import FakeVoiceBackend

        return FakeVoiceBackend
    if settings.voice_backend == "pipeline_local":
        from .voice.pipeline_local import PipelineLocalBackend

        client = _gemini_client(settings)
        return lambda: PipelineLocalBackend(
            client=client, model=settings.gemini_text_model, settings=settings
        )
    if settings.voice_backend == "gemini_live":
        from .voice.gemini_live import GeminiLiveBackend

        client = _gemini_client(settings)
        return lambda: GeminiLiveBackend(client=client, model=settings.gemini_live_model)
    raise ValueError(f"unknown VOICE_BACKEND {settings.voice_backend!r}")


def make_feedback_factory(settings: Settings):
    if settings.voice_backend == "fake":
        return StaticFeedbackGenerator
    client = _gemini_client(settings)
    return lambda: GeminiFeedbackGenerator(client, settings.gemini_text_model)


def create_app(settings: Settings | None = None) -> socketio.ASGIApp:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    api = FastAPI(title="Codeverse API", version="0.2.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    api.include_router(api_router)

    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=settings.cors_origin_list,
        max_http_buffer_size=1_000_000,
        ping_timeout=30,
    )
    bank = get_bank()
    log.info("problem bank: %d problems; voice backend: %s", len(bank), settings.voice_backend)
    register_handlers(
        sio,
        settings=settings,
        bank=bank,
        backend_factory=make_backend_factory(settings),
        feedback_factory=make_feedback_factory(settings),
    )
    return socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")


__all__ = ["create_app", "FeedbackGenerator", "VoiceBackend"]
