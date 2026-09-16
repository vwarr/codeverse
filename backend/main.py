"""Codeverse backend — Phase 0 (server-side audio, Flask-SocketIO).

This is the minimal in-place fix of the original prototype. Audio still runs on
the machine hosting this process (server mic + speakers), so it only works when
the browser and this server are on the same computer. Phases 1–2 replace it.
"""

import os
import threading

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from google import genai
from google.genai import types

from tts import text_to_speech

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
PORT = int(os.getenv("PORT", "5100"))
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
app = Flask(__name__)
CORS(app, origins=CORS_ORIGINS)
socketio = SocketIO(app, cors_allowed_origins=CORS_ORIGINS)

PROMPTS = {
    "swe": (
        "You're conducting a coding interview on the LeetCode question '{problem}'. "
        "Output only ONE SENTENCE. This is extremely important: NEVER write code or prepend your role. "
        "Every response will be read aloud, so never include special characters like backticks or parentheses. "
        "If the candidate says anything that can't reasonably be part of the topic material of the interview, "
        "guide the candidate back on track. Prompt them to describe their intended algorithm before asking them to code. "
        "If the candidate asks for time, acknowledge it and wait for them to continue. "
        "Each candidate message is prefixed with their current code."
    ),
    "ib": (
        "You're conducting an investment banking interview. Output only ONE SENTENCE. "
        "This is extremely important: NEVER include any spreadsheets, financial models, or prepend your role. "
        "Every response will be read aloud, so never include special characters like backticks, parentheses, or brackets. "
        "If the candidate says anything that isn't directly relevant to investment banking, gently guide them back on track. "
        "Prompt them to describe their intended financial approach or valuation methodology before asking for any detailed calculations. "
        "If the candidate asks for time, acknowledge it and wait for them to continue."
    ),
}

INTRO_SOUNDS = {"swe": os.getenv("INTRO_PATH"), "ib": os.getenv("FINANCE_PATH")}
END_SOUND = os.getenv("END_PATH")

# Single-interview state. Phase 1 replaces this with per-connection sessions.
state = {"code": "", "active": False, "thread": None}


@socketio.on("connect")
def handle_connect():
    print("Client connected")


@socketio.on("send_code")
def handle_code_submission(data):
    code = (data or {}).get("code")
    if code is not None:
        state["code"] = code


@socketio.on("start_interview")
def handle_start_interview(data):
    """data: {"track": "swe" | "ib", "problem": "<problem title>"}"""
    if state["active"]:
        emit("error", {"message": "An interview is already running."})
        return
    data = data if isinstance(data, dict) else {"track": str(data or "swe")}
    track = data.get("track", "swe")
    if track not in PROMPTS:
        emit("error", {"message": f"Unknown track '{track}'."})
        return
    problem = data.get("problem", "")
    state["active"] = True
    state["code"] = ""
    emit("interview_started", {"track": track, "problem": problem})
    state["thread"] = socketio.start_background_task(run_interview, track, problem)


@socketio.on("end_interview")
def handle_end_interview():
    state["active"] = False
    print("Interview ended by user")
    emit("interview_ended", {"message": "Interview has ended."})


def _play(path):
    if not path:
        return
    try:
        from playsound import playsound

        playsound(path)
    except Exception as exc:  # noqa: BLE001 — audio is best-effort
        print("playsound failed:", exc)


def _play_async(path):
    done = threading.Event()

    def target():
        _play(path)
        done.set()

    threading.Thread(target=target, daemon=True).start()
    return done


def run_interview(track, problem):
    """Interview loop. Runs in a background task; server mic + speakers."""
    from RealtimeSTT import AudioToTextRecorder

    print(f"Starting {track} interview on {problem!r} with {GEMINI_MODEL}")
    intro_done = _play_async(INTRO_SOUNDS.get(track))

    try:
        recorder = AudioToTextRecorder()
        chat = client.chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(system_instruction=PROMPTS[track].format(problem=problem)),
        )

        intro_done.wait()
        opening = chat.send_message("Greet the candidate briefly and invite them to begin.")
        print("AI:", opening.text)
        socketio.emit("status_update", {"status": "Status 3"})
        text_to_speech(opening.text)

        while state["active"]:
            socketio.emit("status_update", {"status": "Status 1"})
            speech = recorder.text()
            if not state["active"]:
                break
            socketio.emit("status_update", {"status": "Status 2"})

            if track == "swe":
                code = state["code"] or "No code written yet"
                message = f"Current code:\n{code}\n\nCandidate: {speech}"
            else:
                message = speech
            print("Candidate:", speech)

            response = chat.send_message(message)
            print("AI:", response.text)
            if not state["active"]:
                break

            socketio.emit("status_update", {"status": "Status 3"})
            text_to_speech(response.text)

        # Final turn: the feedback the prompt always promised but never delivered.
        socketio.emit("status_update", {"status": "Status 2"})
        closing = chat.send_message(
            "The interview is over. In two or three sentences, give the candidate honest feedback "
            "on their performance, naming one strength and one specific thing to improve."
        )
        print("AI (feedback):", closing.text)
        socketio.emit("status_update", {"status": "Status 3"})
        text_to_speech(closing.text)
        socketio.emit("feedback", {"text": closing.text})
    except Exception as exc:  # noqa: BLE001
        print("Interview loop failed:", repr(exc))
        socketio.emit("error", {"message": f"Interview stopped: {exc}"})
    finally:
        state["active"] = False
        try:
            recorder.shutdown()  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        _play(END_SOUND)
        socketio.emit("status_update", {"status": "Status 0"})
        socketio.emit("interview_ended", {"message": "Interview has ended."})


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=PORT, debug=DEBUG, use_reloader=False)
