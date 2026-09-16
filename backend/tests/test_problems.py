import random
import unittest

from codeverse.problems.bank import Problem, ProblemBank, load_bank


class ProblemBankTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = load_bank()

    def test_bank_loads_and_covers_every_track(self) -> None:
        self.assertGreaterEqual(len(self.bank), 40)
        for track in ("swe", "ib", "quant"):
            self.assertTrue(self.bank.list(track=track), track)

    def test_swe_has_every_difficulty(self) -> None:
        for d in ("easy", "medium", "hard"):
            self.assertTrue(self.bank.list(track="swe", difficulty=d), d)

    def test_listing_is_sorted_by_difficulty_then_title(self) -> None:
        order = {"easy": 0, "medium": 1, "hard": 2}
        listed = self.bank.list(track="swe")
        keys = [(order[p.difficulty], p.title) for p in listed]
        self.assertEqual(keys, sorted(keys))

    def test_random_respects_filters(self) -> None:
        rng = random.Random(1)
        for _ in range(20):
            p = self.bank.random(track="swe", difficulty="hard", rng=rng)
            self.assertEqual((p.track, p.difficulty), ("swe", "hard"))
        with self.assertRaises(LookupError):
            self.bank.random(track="ib", difficulty="hard")

    def test_public_hides_hints_and_tests(self) -> None:
        p = self.bank.get("two-sum")
        assert p is not None
        pub = p.public()
        self.assertNotIn("hints", pub)
        self.assertNotIn("tests", pub)
        self.assertIn("statement", pub)
        self.assertIn("starter_code", pub)

    def test_prompt_text_includes_examples_and_hints(self) -> None:
        p = self.bank.get("best-time-to-buy-and-sell-stock")
        assert p is not None
        text = p.prompt_text()
        self.assertIn("Example 1", text)
        self.assertIn("output 5", text)
        self.assertIn("Hints you may offer", text)

    def test_swe_problems_have_python_starter_and_function_name(self) -> None:
        for p in self.bank.list(track="swe"):
            self.assertIn("python", p.starter_code, p.id)
            self.assertTrue(p.function_name, p.id)

    def test_tests_reference_the_function_arity_sanely(self) -> None:
        for p in self.bank.list(track="swe"):
            for t in p.tests:
                self.assertIsInstance(t.args, list, p.id)

    def test_duplicate_ids_rejected(self) -> None:
        p = Problem(id="x", track="swe", title="X", difficulty="easy", statement="s")
        with self.assertRaises(ValueError):
            ProblemBank([p, p])

    def test_bad_slug_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Problem(id="not a slug", track="swe", title="X", difficulty="easy", statement="s")


if __name__ == "__main__":
    unittest.main()
