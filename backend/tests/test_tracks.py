import unittest

from codeverse.interview import prompts
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
        p = self.bank.list(track="ib")[0]
        text = get_track("ib").system_prompt(p, extra_rules="Be adversarial.")
        self.assertTrue(text.endswith("Be adversarial."))

    def test_unknown_track(self) -> None:
        with self.assertRaises(LookupError):
            get_track("nope")

    def test_public_shape(self) -> None:
        pub = get_track("swe").public()
        self.assertEqual(pub["surface"], "editor")
        self.assertEqual(get_track("ib").public()["surface"], "conversation")

    def test_prompt_version_is_set(self) -> None:
        self.assertRegex(prompts.PROMPT_VERSION, r"^\d{4}-\d{2}-\d{2}\.\d+$")


if __name__ == "__main__":
    unittest.main()
