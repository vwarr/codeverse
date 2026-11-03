# Codeverse backend

This directory holds the Python code for Codeverse. See the repository README for the overview.

- `codeverse/web/`, `interview/`, `problems/`, `execution/`: used by the Vercel functions in `/api`.
- `codeverse/app.py`, `sockets.py`, `sessions.py`, `voice/`, `problems/api.py`, `Dockerfile`, `fly.toml`: the **legacy** FastAPI + Socket.IO server. The frontend does not use it.

```sh
cd backend
uv sync --extra dev
uv run pytest                # no network: Gemini and Neon are faked
uv run python -m codeverse   # legacy server only, http://localhost:5100
```

Settings come from environment variables and from `backend/.env` (see `.env.example`).
