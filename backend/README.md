# Codeverse backend

This directory holds the Python code for Codeverse. See the repository README for the overview.

- `codeverse/web/`: the routes, the HTTP handler and the Neon store for the Vercel functions in `/api`.
- `codeverse/interview/`, `problems/`, `execution/`, `config.py`: the prompts, tracks, tools, report, problem bank, code runners and settings. The functions use them.

```sh
cd backend
uv sync --extra dev
uv run pytest      # no network: Gemini and Neon are faked
uv run ruff check
```

Settings come from environment variables and from `backend/.env` (see `.env.example`).
