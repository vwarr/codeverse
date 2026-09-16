# Codeverse

Codeverse is an AI mock interviewer you talk to. Pick a track — software engineering, investment banking, or quant — and a problem; the interviewer introduces it, listens while you think aloud, asks follow-ups, watches your code, and at the end gives you a spoken summary plus a written report scored against a rubric.

## How it works

```
Browser (React + Monaco)                 Backend (FastAPI + python-socketio)            Gemini
┌──────────────────────────┐   audio_in   ┌────────────────────────────────────┐
│ mic → AudioWorklet 16 kHz├─────────────►│ InterviewSession (per client)      │  Live API
│ speaker ◄ PCM 24 kHz     │◄─────────────┤   state machine · transcript       ├◄────────►  audio in/out,
│ editor → code_update     ├─────────────►│   code snapshot · latency metrics  │            transcripts,
│ transcript / state ◄─────│◄─────────────┤ VoiceBackend ── GeminiLiveBackend  │            tool calls
└──────────────────────────┘              │ tools: get_current_code, wrap_up   │
                                          │ FeedbackReport (JSON schema)       ├──────────►  text model
                                          │ /api/problems · /api/tracks        │
                                          └────────────────────────────────────┘
```

- Audio is captured and played in the browser; the backend is a per-session proxy, so the app can be deployed anywhere.
- The voice provider sits behind a small `VoiceBackend` interface (`backend/codeverse/voice/base.py`). Gemini Live is the first implementation; `fake` is a scripted one for tests and UI work; `pipeline_local` is the original server-mic prototype kept for reference.
- The interviewer can call tools: `get_current_code` to read the editor, `request_wrap_up` to end the interview when it has covered its phases.
- After the interview a text model writes a structured `FeedbackReport` (scores per rubric dimension, strengths, improvements, a model answer sketch, notable moments).
- Every model turn's response latency (end of your speech → first audio byte) is measured and shown on the report page.

## Run it locally

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```sh
cd backend
uv sync
cp .env.example .env        # set GEMINI_API_KEY
uv run python -m codeverse  # http://localhost:5100
```

Frontend (Node 22):

```sh
npm install
npm run dev                 # http://localhost:5173
```

Open the app, allow the microphone, pick a track and press Start. To work on the UI without spending API calls, set `VOICE_BACKEND=fake` in `backend/.env`.

## Tests and checks

```sh
cd backend && uv run pytest      # session state machine, socket handlers, problem bank, Live reconnect loop
npm test                         # typecheck, prettier, eslint, vitest, build
```

## Deploy

- Backend: `backend/Dockerfile` + `backend/fly.toml` (Fly.io; any host with WebSocket support and a persistent process works). Set `GEMINI_API_KEY` as a secret and `CORS_ORIGINS` to the frontend origin.
- Frontend: static Vite build; `vercel.json` rewrites routes to `index.html`. Set `VITE_BACKEND_URL` to the backend URL.
- Guardrails for a public URL: `MAX_SESSION_MINUTES` and `MAX_SESSIONS_PER_IP` in the backend env, plus a spend cap on the Gemini key. Live audio is billed per token.

## Configuration

All backend settings are environment variables; see `backend/.env.example`. Model IDs (`GEMINI_LIVE_MODEL`, `GEMINI_TEXT_MODEL`) are deliberately config, not code — they drift.

## Layout

```
backend/codeverse/
  app.py, sockets.py, sessions.py, config.py
  voice/        base.py · gemini_live.py · fake.py · pipeline_local.py
  interview/    tracks.py · prompts.py · tools.py · feedback.py
  problems/     bank.json · bank.py · api.py
src/
  lib/          socket.ts · api.ts · types.ts · audio/{capture,player,engine}.ts
  state/        interview.ts (reducer) · InterviewProvider.tsx
  pages/        Home · Interview · Feedback
  components/   ProblemPanel · CodePane · Transcript · StatusBadge · InterviewerAvatar
```

## Roadmap

- Code execution against the bank's hidden tests (Piston), exposed to the interviewer as a `run_tests` tool
- Session persistence and a history page with trends per rubric dimension
- A second `VoiceBackend`: browser audio → server VAD → Whisper → text model → streaming TTS, to benchmark against Live
- More problems, interviewer personas, a system-design track
