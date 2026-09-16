"""Tests the SDK-independent parts of the Gemini Live backend with stand-in message objects."""

import unittest
from types import SimpleNamespace as NS

from codeverse.voice.gemini_live import translate_message


def msg(**kw):
    base = {"tool_call": None, "server_content": None, "session_resumption_update": None, "go_away": None}
    base.update(kw)
    return NS(**base)


class TranslateMessageTests(unittest.TestCase):
    def test_audio_parts_become_audio_events(self) -> None:
        m = msg(
            server_content=NS(
                model_turn=NS(
                    parts=[
                        NS(inline_data=NS(data=b"\x00\x01")),
                        NS(inline_data=None),
                        NS(inline_data=NS(data=b"")),
                    ]
                ),
                input_transcription=None,
                output_transcription=None,
                interrupted=None,
                turn_complete=None,
            )
        )
        events = translate_message(m)
        self.assertEqual([e.kind for e in events], ["audio"])
        self.assertEqual(events[0].audio, b"\x00\x01")

    def test_transcripts_and_turn_boundaries(self) -> None:
        m = msg(
            server_content=NS(
                model_turn=None,
                input_transcription=NS(text="hello"),
                output_transcription=NS(text="hi there"),
                interrupted=None,
                turn_complete=True,
            )
        )
        events = translate_message(m)
        self.assertEqual([e.kind for e in events], ["user_transcript", "model_transcript", "turn_complete"])
        self.assertEqual(events[0].text, "hello")

    def test_interrupted(self) -> None:
        m = msg(
            server_content=NS(
                model_turn=None,
                input_transcription=None,
                output_transcription=None,
                interrupted=True,
                turn_complete=None,
            )
        )
        self.assertEqual([e.kind for e in translate_message(m)], ["interrupted"])

    def test_tool_calls(self) -> None:
        m = msg(
            tool_call=NS(
                function_calls=[
                    NS(id="c1", name="get_current_code", args=None),
                    NS(id="c2", name="x", args={"a": 1}),
                ]
            )
        )
        events = translate_message(m)
        self.assertEqual(
            [(e.tool_call_id, e.tool_name, e.tool_args) for e in events],
            [("c1", "get_current_code", {}), ("c2", "x", {"a": 1})],
        )

    def test_empty_message(self) -> None:
        self.assertEqual(translate_message(msg()), [])


if __name__ == "__main__":
    unittest.main()
