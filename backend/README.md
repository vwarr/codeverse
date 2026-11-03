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

Score calibration (manual, not run by pytest or CI; it calls the real report model and needs `GEMINI_API_KEY`): `uv run python evals/score_calibration.py --model <model>` runs each synthetic interview in `evals/fixtures/` 3 times (24 calls) and checks the report scores against the expected bands. It refuses the production report model, because on a free key the runs would use the daily quota production reports need. Use `--runs 1 --case swe-strong` for a quick check.

Settings come from environment variables and from `backend/.env` (see `.env.example`).
