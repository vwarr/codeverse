import unittest

from sessionize import SESSION_GAP, Event, average_session_seconds, sessionize

MIN = 60


def ev(user, minute, page="/"):
    return Event(user, 1_700_000_000 + minute * MIN, page)


class SessionizeTests(unittest.TestCase):
    def test_single_burst_is_one_session(self):
        out = sessionize([ev("u1", 0, "/a"), ev("u1", 5, "/b"), ev("u1", 9, "/c")])
        self.assertEqual(len(out["u1"]), 1)
        self.assertEqual(out["u1"][0].pages, ["/a", "/b", "/c"])
        self.assertEqual(out["u1"][0].duration, 9 * MIN)

    def test_long_gap_starts_new_session(self):
        out = sessionize([ev("u1", 0), ev("u1", 5), ev("u1", 5 + 31)])
        self.assertEqual(len(out["u1"]), 2)

    def test_users_are_independent(self):
        out = sessionize([ev("u1", 0), ev("u2", 1), ev("u1", 2)])
        self.assertEqual(len(out["u1"]), 1)
        self.assertEqual(len(out["u2"]), 1)

    def test_gap_of_exactly_the_limit_stays_in_session(self):
        events = [ev("u1", 0), Event("u1", ev("u1", 0).ts + SESSION_GAP, "/")]
        self.assertEqual(len(sessionize(events)["u1"]), 1)

    def test_steady_activity_is_one_long_session(self):
        # A user active every 10 minutes for two hours never goes idle for 30 minutes.
        events = [ev("u1", m) for m in range(0, 121, 10)]
        sessions = sessionize(events)["u1"]
        self.assertEqual(len(sessions), 1, f"got {len(sessions)} sessions for continuous activity")
        self.assertEqual(sessions[0].duration, 120 * MIN)

    def test_out_of_order_events(self):
        events = [ev("u1", 10, "/b"), ev("u1", 0, "/a"), ev("u1", 20, "/c")]
        sessions = sessionize(events)["u1"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].pages, ["/a", "/b", "/c"])
        self.assertGreaterEqual(sessions[0].duration, 0, "session has a negative duration")

    def test_no_negative_durations_with_shuffled_ingest(self):
        events = [ev("u1", m) for m in (50, 0, 100, 5, 55, 105)]
        for s in sessionize(events)["u1"]:
            self.assertGreaterEqual(s.duration, 0)
        self.assertEqual(len(sessionize(events)["u1"]), 3)

    def test_average(self):
        events = [ev("u1", 0), ev("u1", 10), ev("u2", 0), ev("u2", 20)]
        self.assertEqual(average_session_seconds(events), 15 * MIN)
        self.assertEqual(average_session_seconds([]), 0.0)


if __name__ == "__main__":
    unittest.main()
