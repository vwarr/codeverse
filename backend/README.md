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

Score calibration (manual, not run by pytest or CI; it calls the real report model): `uv run python evals/score_calibration.py` grades the 8 synthetic interviews in `evals/fixtures/` once each on `gemini-3.8-flash` and checks the scores against the expected bands. It prints the planned call count first and stops at `--max-calls` (default 12, retries included); use `--runs 3 --max-calls 30` for a variance check. Free-tier quota is per model and per day and shared with production: calibrating the production model means `--model gemini-3.6-flash` with a small budget (for example `--case swe-mediocre --max-calls 3`), since that model has only 20 calls a day for real reports.

Settings come from environment variables and from `backend/.env` (see `.env.example`).
