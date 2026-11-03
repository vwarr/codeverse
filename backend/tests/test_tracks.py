import unittest

from codeverse.interview import prompts
from codeverse.interview.feedback import RUBRICS, build_feedback_prompt
from codeverse.interview.tracks import TRACKS, get_track
from codeverse.problems.bank import load_bank


class TrackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = load_bank()

    def test_every_track_builds_a_prompt_for_every_problem(self) -> None:
        # Valid Parentheses contains literal braces; str.format must not choke on problem text.
        for track in TRACKS.values():
            for problem in self.bank.list(track=track.id):
                text = track.system_prompt(problem)
                self.assertIn(problem.title, text)
                self.assertIn("request_wrap_up", text)
                self.assertNotIn("{problem}", text)

    def test_swe_prompt_mentions_code_tool(self) -> None:
        p = self.bank.get("valid-parentheses")
        assert p is not None
        text = get_track("swe").system_prompt(p)
        self.assertIn("get_current_code", text)
        self.assertIn("{", p.statement)  # the brace case is really exercised

    def test_extra_rules_are_appended(self) -> None:
        p = self.bank.list(track="debug")[0]
        text = get_track("debug").system_prompt(p, extra_rules="Be adversarial.")
        self.assertTrue(text.endswith("Be adversarial."))

    def test_unknown_track(self) -> None:
        with self.assertRaises(LookupError):
            get_track("nope")

    def test_public_shape(self) -> None:
        pub = get_track("swe").public()
        self.assertEqual(pub["surface"], "editor")

    def test_every_track_has_a_rubric(self) -> None:
        for track_id in TRACKS:
            self.assertTrue(RUBRICS.get(track_id), track_id)

    def test_debug_track_shape(self) -> None:
        t = get_track("debug")
        pub = t.public()
        self.assertEqual(pub["surface"], "editor")
        self.assertEqual(pub["languages"], ["python"])
        self.assertTrue(pub["canRun"])
        self.assertIn("get_last_test_run", t.tool_names)
        self.assertIn("get_current_code", t.tool_names)
        swe = get_track("swe").public()
        self.assertTrue(swe["canRun"])
        self.assertEqual(swe["languages"], ["python"])
        self.assertFalse(get_track("swe").grade_final_run)
        self.assertTrue(t.grade_final_run)

    def test_debug_prompt_includes_code_bugs_and_phases(self) -> None:
        p = self.bank.get("deploy-order")
        assert p is not None
        text = get_track("debug").system_prompt(p)
        self.assertIn("debugging interview", text)
        self.assertIn("class Resolver:", text)  # braces in the code survive str.format
        self.assertIn("{node!r}", p.reference_solution or "")
        self.assertIn("PLANTED BUGS (3)", text)
        self.assertIn("get_last_test_run", text)
        self.assertIn("Run tests", text)
        self.assertIn("never name", text)

    def test_debug_feedback_prompt_includes_final_test_result(self) -> None:
        text = build_feedback_prompt(
            track_id="debug",
            problem_text="P",
            transcript=[{"role": "candidate", "text": "hi"}],
            code="x = 1",
            test_summary="3 of 8 tests passed.",
        )
        self.assertIn("TEST SUITE RESULT", text)
        self.assertIn("3 of 8 tests passed.", text)
        self.assertIn("Root cause", text)

    def test_prompt_version_is_set(self) -> None:
        self.assertRegex(prompts.PROMPT_VERSION, r"^\d{4}-\d{2}-\d{2}\.\d+$")


if __name__ == "__main__":
    unittest.main()
