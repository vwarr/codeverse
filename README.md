# Codeverse

Codeverse is an AI mock interviewer you talk to. Pick a track — software engineering or debugging — and a problem; the interviewer introduces it, listens while you think aloud, asks follow-ups, watches your code, and at the end gives you a spoken summary plus a written report scored against a rubric.

## How it works

```
Browser (React + Monaco)                                Gemini
┌───────────────────────────────────┐   Live API (WebSocket, ephemeral token)
│ mic → AudioWorklet 16 kHz         ├────────────────►  audio in/out, transcripts,
│ speaker ◄ PCM 24 kHz (gapless)    │◄────────────────   tool calls
│ LiveInterview: state machine,     │
│   transcript, latency, tools      │
└──────┬────────────────────────────┘
       │ fetch /codeverse/api/*
┌──────▼────────────────────────────┐
│ Vercel functions (Python, api/)   │
│  session    mint a one-use token  ├──────────────►  auth_tokens (model, prompt, tools locked)
│  run_tests  hidden unittest suite ├──────────────►  Vercel Sandbox (one microVM per run)
│  report     FeedbackReport        ├──────────────►  text model
│  history    reports for client ID │
│  tracks · problems                │
└──────┬────────────────────────────┘
       ▼ Neon Postgres: interview_sessions, interview_reports
```

- The browser talks to Gemini Live directly. There is no long-running server.
- `POST /api/session` picks the problem and checks the per-address limit. Then it mints a Gemini Live ephemeral token. The token has one use and a short life. The token locks the model, the system instruction, the tool declarations and the voice on Google's side. The browser never sees the interviewer prompt. This matters for the debugging track, because its prompt names the planted bugs.
- The browser runs the interview (`src/lib/live/LiveInterview.ts`). It sends microphone audio, plays the reply, keeps the transcript and measures the latency of each model turn (end of your speech to the first audio byte). It answers the tool calls itself: `get_current_code` (the editor), `get_last_test_run` (debugging track) and `request_wrap_up`. The Live API closes each connection after about ten minutes. The browser then reconnects with the session-resumption handle and the same token.
- The tool declarations set `behavior: BLOCKING`. The Live model waits for each tool result before it speaks, so it does not talk about code or test results that it has not seen.
- **Debugging track**: the candidate gets a bug report and a broken Python module. **Run tests** calls `POST /api/run_tests`. That function runs a hidden `unittest` suite on the editor code in a new Vercel Sandbox (see [Code execution](#code-execution)). The suite stays on the server. The interviewer knows the planted bugs and does not reveal them. At the end, the suite runs again on the final code and the result goes into the report. Problems are in `backend/codeverse/problems/debug/` (see the README there).
- **Software-engineering track**: **Run tests** also calls `POST /api/run_tests`. The function makes a `unittest` suite from the problem's hidden `tests` in `bank.json` and runs it on `solution.py`. Only the results go back to the browser. 18 of the 27 problems have tests. For the other problems, the editor shows no **Run tests** button. Only the debugging track grades the final code in the report.
- At the end, `POST /api/report` sends the transcript, the code and the metrics. The function saves the transcript in Neon first (status `pending`). Then a text model writes a structured `FeedbackReport`, and the status changes to `complete`. `GET /api/report?sessionId=…` reads the record back.
- Rate limits: the report function retries the text model after a 429 or 5xx error (`REPORT_RETRY_DELAYS`). If the model still fails, the record keeps the transcript with the status `failed`, and a later `POST /api/report` for the same session tries again. If the Live connection closes because of a rate limit or quota error, the browser does not reconnect. It ends the interview, keeps the transcript and still asks for the report. A lost connection after the interview started has the same result.
- The functions reuse the Python modules in `backend/codeverse` (prompts, tracks, problems, feedback, execution). The new code is in `backend/codeverse/web/`.

## User interface

The app is served under `/codeverse/` (it lives at https://varunwarrier.com/codeverse, which rewrites `/codeverse/*` to this project). The page paths below are relative to that prefix, so the History page is `/codeverse/history`. The browser calls the functions at `/codeverse/api/*`; this README names them by their function path (`/api/*`).

All problems are in Python. There is no language picker.

- **Start page** (`/`): select a track (Software engineering or Debugging), a difficulty and a problem. Then press **Start interview**. The **History** link opens the list of past reports. The line "Demo: scripted interviewer" shows only in demo mode.
- **Interview page** (`/interview`): three columns. The left column shows the problem. On the debugging track, it shows the bug report and the module name. The middle column has the editor, **Run tests** and the **Output** area with the test results. The right column shows the transcript.
- The header shows one status line (`role="status"`), the time left, **Mute** and **Finish**. These states have a message:
  - Connecting to the interviewer.
  - Reconnecting: the voice connection dropped and the browser resumes the same interview.
  - Microphone blocked: the interview does not start. The message tells you to allow the microphone.
  - Muted: the microphone sends silence. Press **Unmute** to speak again.
  - Time left: a message shows 5 minutes before the end. At 0:00 the interviewer starts the wrap-up.
  - The interviewer started the wrap-up (the `request_wrap_up` tool).
- **Report page** (`/feedback`, and `/report/<sessionId>` for a saved report): the overall score, the summary, the rubric for the track, "Went well" and "Work on", the tests on the final code (debugging track), a sketch of a strong answer, notable moments, the median response latency and the transcript.
- **History page** (`/history`): the reports from interviews in this browser, newest first. There are no accounts. The browser makes a random client ID (`crypto.randomUUID()`) one time and keeps it in `localStorage` (`cv_client_id`). It sends the ID with `POST /api/session`, and the session row keeps it (`client_id`). `GET /api/history` needs the header `X-Client-Id`. It lists only the complete reports for that ID, with summary fields only. If the ID is missing or not a UUID, it returns 400. It never lists reports for other IDs. Keep the ID secret, because it works like a password. The IP is used only for the session limit. If you clear the browser storage, the History page starts empty. A saved report stays available at `/report/<sessionId>`.
- **Early end**: if the interviewer hits a usage limit or the voice connection is lost, the report page shows why the interview ended early.

### Design

- The theme is in `src/theme.ts` (Mantine) and `src/global.css` (layout and colour variables). Do not use inline colours in components. Use the theme tokens.
- Fonts: IBM Plex Sans for text and IBM Plex Mono for code (Google Fonts, in `index.html`).
- Colours: background `#F6F6F4`, text `#1A1A19`, muted text `#5E5E5A`, borders `#DADAD5` and `#B9B9B3`, surfaces `#FFFFFF` and `#ECECE8`, and one accent `#C2410C`. Use the accent for text only on `#F6F6F4` or `#FFFFFF` (contrast 4.8:1 and 5.2:1). On `#ECECE8`, its contrast is less than 4.5:1.
- Shape: 4 px radius, hairline borders, no shadows and no gradients. Primary buttons are dark (`#1A1A19`, hover `#3A3A38`).
- Accessibility: every control has a visible focus outline (2 px, offset 2 px). The track and difficulty pickers use `fieldset` and `legend`. Status changes use `role="status"` or `aria-live`.

### Demo mode

`VITE_DEMO=1 npm run dev` plays a scripted interview. It does not use the API, Gemini or the microphone.

- **Run tests** shows real results from the hidden suites. For the software-engineering track, these results are for the starter code only (`src/lib/demo/sweRuns.json`). For the debugging track, they are for the starter code and the fixed code (`src/lib/demo/debugRuns.json`).
- The demo saves reports in `localStorage`, so the History page shows them.
- To see one interview state, add `?demoState=` before the `#`. The values are `reconnecting`, `mic_denied` and `interviewer_wrap_up`. Example: `http://localhost:5173/codeverse/?demoState=reconnecting#/`.
- Demo mode is for local UI work and screenshots only. A Vercel build with `VITE_DEMO` set fails (see `vite.config.mjs`), so production never ships it.
- To make `sweRuns.json` again after a change to the bank, run each problem's starter code with `job_for` and `LocalRunner` (see `backend/tests/test_jobs.py`).

## Run it locally

You need Node 22, Python 3.14, [uv](https://docs.astral.sh/uv/) and the [Vercel CLI](https://vercel.com/docs/cli). The repository is linked to the Vercel project `codeverse`.

1. Install the frontend packages: `npm install`.
2. Put the Gemini API key in `backend/.env` as `GEMINI_API_KEY=…`. The functions read this file. (The Vercel copy of the key is sensitive, so `vercel env pull` cannot download it.)
3. Get the Neon variables and the OIDC token for Vercel Sandbox: `vercel env pull .env.local`. The OIDC token expires after about 12 hours. Run the command again when **Run tests** fails with a credentials error.
4. Start the app: `vercel dev`. Open the URL that it shows (http://localhost:3000); `/` redirects to `/codeverse/`.
5. Allow the microphone, select a track and press **Start interview**.

`vercel dev` runs Vite and the Python functions together. It installs the packages in `requirements.txt` for the version in `.python-version`, but it runs your local `python3`. These two versions must be the same.

To work on the UI without the API or Gemini, run `VITE_DEMO=1 npm run dev`. Demo mode plays a scripted interview in the browser.

## Tests and checks

```sh
cd backend && uv run pytest      # functions (token, run_tests, report) with a fake Gemini and an in-memory store,
                                 # problem bank and runner
npm test                         # typecheck, prettier, eslint, stylelint, vitest (incl. LiveInterview), build
```

The tests do not call Gemini or Neon.

## Deploy

A push to the GitHub repository deploys to Vercel (Hobby tier is sufficient).

1. Make sure that the Vercel project has these environment variables: `GEMINI_API_KEY`, and the Neon variables (`DATABASE_URL` and the others that the Neon integration adds).
2. Optional: set the variables in the table below to change the defaults.
3. Push the branch. Vercel builds the Vite app and makes one function for each file in `api/`.
4. The first request that uses the database creates the tables (`CREATE TABLE IF NOT EXISTS`). You do not have to run a migration.

`vercel.json` does these things:

- It adds `backend/codeverse/**` to each function bundle. It keeps the hidden test files (`problems/debug/*/test_*.py`) in the bundle.
- Vite builds into `dist/codeverse/` (`base: '/codeverse/'`), and `outputDirectory` is `dist`, so the assets exist at `/codeverse/assets/...`. Vercel serves files before it applies rewrites, so the assets need no rule.
- It rewrites `/codeverse/api/*` to the functions at `/api/*`, and every other path under `/codeverse/` to `/codeverse/index.html`, so the SPA routes work. It redirects `/` to `/codeverse/`.
- varunwarrier.com (a separate Vercel project) rewrites `/codeverse` and `/codeverse/*` to this project's production URL.

Do not add `fastapi` or `flask` to `requirements.txt`. If you do, Vercel detects a Python framework and sends every request to it, not to the Vite app.

Guardrails for a public URL:

- `MAX_SESSION_MINUTES`: the browser starts the wrap-up at this time. The token expires `SESSION_GRACE_MINUTES` later, and then Gemini rejects all messages.
- `MAX_SESSIONS_PER_IP`: the number of interviews for one address whose token has not expired. The address comes from `x-vercel-forwarded-for`, then `x-real-ip`, then `x-forwarded-for` (`client_ip` in `backend/codeverse/web/handler.py`). Vercel sets these. Its docs do not say what a Vercel deployment sees when another Vercel project (varunwarrier.com) rewrites to it; check `interview_sessions.ip` after a deploy. A token cannot be revoked, so an interview counts until its token expires (`MAX_SESSION_MINUTES` + `SESSION_GRACE_MINUTES`), also after it ends. A reloaded tab also uses a slot.
- Set a spend cap on the Gemini key. Live audio is billed per token.
- Vercel Sandbox on Hobby: 5,000 sandbox creations, 5 hours of active CPU and 10 concurrent sandboxes each month. Each **Run tests** press and each final grading uses one sandbox. When the quota is used, Vercel pauses sandbox creation, and **Run tests** fails until the next cycle. Lower `MAX_RUNS_PER_SESSION` to make the quota last longer.

### Code execution

Candidate code never runs in a function. Vercel environment variables apply to the whole project, so every function has `GEMINI_API_KEY` and `DATABASE_URL`. A child process of a function can read them.

- `CODE_RUNNER=sandbox` (the default): each run gets a new Vercel Sandbox (a Firecracker microVM). The function sends in the code, the tests and the harness, and reads back the results file. The sandbox has no environment variables and a deny-all network policy. It stops after the run. The SDK authenticates with the project's OIDC token, so you do not have to add a secret.
- `CODE_RUNNER=local`: a child process with a timeout and rlimits. Use it for local development only. The functions refuse it on a Vercel deployment (`VERCEL_ENV` is `production` or `preview`) and turn code execution off.
- `CODE_EXECUTION_ENABLED=false` turns **Run tests** off.

The runner interface is `codeverse.execution`: `job_for(problem, code)` makes a `TestJob`, and `CodeRunner.run(job)` returns a `RunResult`. The debugging track uses the problem's hidden `unittest` file. The software-engineering track uses a suite made from the `tests` in `bank.json` (`args` and `expected`), which calls `function_name` in `solution.py`. The suite changes tuples to lists before it compares. Some problems accept the items of the answer in any order. For these problems, set `"compare": "any_order"` in `bank.json`. The suite then sorts the two lists before it compares them. At this time, only `two-sum` has this flag. `group-anagrams` and `top-k-frequent-elements` also accept any order, but they have no tests. If you add tests to them, add the flag too. A nested answer (a list of groups) needs more than one sort level, which the flag does not do.

## Configuration

All settings are environment variables (see `backend/.env.example`). Model IDs are configuration, not code, because they change.

| Variable | Default | Use |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Mints tokens and writes reports. Never sent to the browser. |
| `GEMINI_LIVE_MODEL` | `gemini-3.8-live` | The Live model. The token locks it. |
| `GEMINI_TEXT_MODEL` | `gemini-3.6-flash` | The model that writes the report. |
| `GEMINI_LIVE_API_VERSION` | `v1beta` | API version for tokens and the browser connection. Google's docs say that tokens work only with `v1beta`. |
| `LIVE_VOICE` | `Kore` | The interviewer voice. |
| `DATABASE_URL` | — | Neon Postgres (pooled connection string). |
| `MAX_SESSION_MINUTES` | `45` | Length of an interview. |
| `SESSION_GRACE_MINUTES` | `3` | Extra token life for the closing turn. |
| `MAX_SESSIONS_PER_IP` | `2` | Open interviews for one address. |
| `CODE_EXECUTION_ENABLED` | `true` | Turns **Run tests** on or off. |
| `CODE_RUNNER` | `sandbox` | `sandbox` (Vercel Sandbox) or `local` (development only). |
| `REPORT_RETRY_DELAYS` | `[2, 8]` | Seconds to wait before each retry of the report model after a 429 or 5xx error. |
| `CODE_RUN_TIMEOUT_SECONDS` | `6` | Time limit for one test run. |
| `MAX_RUNS_PER_SESSION` | `20` | Test runs for one interview. |

## Layout

```
api/                      Vercel functions: tracks · problems · session · run_tests · report · end · history
backend/codeverse/
  web/          service.py (routes) · handler.py (HTTP) · store.py (Neon)
  interview/    tracks.py · prompts.py · tools.py · feedback.py
  problems/     bank.json · bank.py · debug/<problem>/{problem.json,buggy.py,fixed.py,test_*.py}
  execution/    jobs.py (TestJob, CodeRunner, job_for) · sandbox.py (Vercel Sandbox) · runner.py (local) · _harness.py
src/
  lib/          api.ts · transport.ts · types.ts · live/{LiveInterview,connector}.ts · audio/{capture,player,engine}.ts
  state/        interview.ts (reducer) · InterviewProvider.tsx
  lib/demo/     demoSocket.ts (scripted interview) · history.ts (localStorage) · *.json
  pages/        Home · Interview · Feedback · Report · History
  components/   AppHeader · Logo · ProblemPanel · CodePane · TestResults · Transcript · ReportView
  theme.ts · global.css     design tokens and layout
```

## Roadmap

- Tests for the software-engineering problems that have none (linked lists, LRU cache and others)
- Trends per rubric dimension on the History page
- A second voice path: browser audio → server VAD → Whisper → text model → streaming TTS, to benchmark against Live
- More problems, interviewer personas, a system-design track
