"""The seam between the interview session and whichever voice provider is in use.

A VoiceBackend owns one live conversation. It receives the candidate's audio and
text context, and yields VoiceEvents: audio to play, transcripts of both sides,
turn boundaries, interruptions, tool calls. The session layer never imports a
provider SDK; providers never import the session layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

EventKind = Literal[
    "audio",  # model speech, PCM16 mono at output_sample_rate
    "user_transcript",  # fragment of what the candidate said (may be partial)
    "model_transcript",  # fragment of what the interviewer said
    "turn_complete",  # the model finished a turn; back to listening
    "interrupted",  # candidate barged in; discard buffered playback
    "tool_call",  # model wants a tool run; reply with send_tool_result
    "error",
    "closed",  # provider closed the conversation
]


@dataclass(slots=True)
class VoiceEvent:
    kind: EventKind
    audio: bytes | None = None
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str | None = None
    message: str | None = None  # for "error" / "closed"


@dataclass(slots=True)
class ToolSpec:
    """Provider-agnostic function declaration. `parameters` is a JSON schema object."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None

    def declaration(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@runtime_checkable
class VoiceBackend(Protocol):
    input_sample_rate: int  # what the browser must send
    output_sample_rate: int  # what the browser will receive

    async def start(self, *, system_prompt: str, tools: list[ToolSpec], voice: str | None = None) -> None:
        """Open the conversation. Must be called before anything else."""

    async def send_audio(self, pcm16: bytes) -> None:
        """Stream candidate audio (PCM16 mono at input_sample_rate)."""

    async def send_context(self, text: str) -> None:
        """Add text to the model's context WITHOUT triggering a response."""

    async def request_turn(self, text: str) -> None:
        """Send text that DOES trigger a model turn (opening line, wrap-up)."""

    async def send_tool_result(self, call_id: str, name: str, result: dict[str, Any]) -> None: ...

    def events(self) -> AsyncIterator[VoiceEvent]:
        """Yield events until the conversation closes."""
        ...

    async def close(self) -> None: ...
