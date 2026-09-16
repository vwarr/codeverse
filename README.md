# Codeverse

Codeverse is an AI-powered technical interviewer that simulates software engineering and finance interviews with a live, spoken conversation. It asks follow-ups, nudges you back on track, and gives feedback on how you communicated and solved the problem.

## Features

- **Live spoken interview** – the interviewer listens, thinks, and talks back in real time.
- **SWE track** – a coding problem in a Monaco editor; the interviewer sees your code as you type.
- **IB track** – a conversational investment-banking interview.
- **Closing feedback** – a short spoken assessment when you finish.

## Tech stack

- **Frontend**: React, TypeScript, Mantine, Monaco, Socket.IO client
- **Backend**: Flask + Flask-SocketIO, Gemini API, Google Cloud TTS, RealtimeSTT

> **Current limitation (Phase 0):** speech-to-text and text-to-speech run on the machine hosting the backend, so the browser and the backend must be on the same computer. Moving audio into the browser is the next milestone.

## Setup

1. Backend

   ```sh
   cd backend
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in GEMINI_API_KEY and the audio paths
   python main.py
   ```

   Google Cloud TTS uses application-default credentials (`gcloud auth application-default login`).

2. Frontend

   ```sh
   npm install
   npm run dev
   ```

   Set `VITE_BACKEND_URL` if the backend is not on `http://localhost:5100`.

## Development

```sh
npm test          # typecheck, prettier, eslint, vitest, build
```

## Roadmap

- Browser-side audio via a swappable voice backend (Gemini Live first)
- Structured end-of-interview report
- Problem bank with test cases and code execution
- Session history and progress tracking
