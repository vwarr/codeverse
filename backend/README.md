# Codeverse backend

FastAPI + python-socketio service that runs interviews. See the repository README for the overview.

```sh
cd backend
uv sync                      # or: pip install -e ".[dev]"
cp .env.example .env         # set GEMINI_API_KEY
uv run python -m codeverse   # http://localhost:5100
uv run pytest                # tests use a fake voice backend; no network needed
```

Layout: `codeverse/sessions.py` (state machine), `codeverse/sockets.py` (Socket.IO events), `codeverse/voice/`
(the `VoiceBackend` interface and its implementations), `codeverse/interview/` (tracks, prompts, tools,
feedback), `codeverse/problems/` (bank + REST API).
