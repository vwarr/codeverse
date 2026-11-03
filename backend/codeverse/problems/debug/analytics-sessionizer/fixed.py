"""Group raw click events into user sessions for the analytics dashboard.

A session is a run of events from one user where no two consecutive events are more than
SESSION_GAP seconds apart. Events arrive from several ingest workers, so they are NOT guaranteed
to be in timestamp order.
"""

from collections import defaultdict
from dataclasses import dataclass, field

SESSION_GAP = 30 * 60  # seconds of inactivity that end a session


@dataclass
class Event:
    user_id: str
    ts: int  # unix seconds
    page: str


@dataclass
class Session:
    user_id: str
    start: int
    end: int
    pages: list[str] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return self.end - self.start


def sessionize(events):
    """Return {user_id: [Session, ...]} with each user's sessions in chronological order."""
    by_user = defaultdict(list)
    for ev in events:
        by_user[ev.user_id].append(ev)

    result = {}
    for user_id, user_events in by_user.items():
        sessions = []
        current = None
        for ev in sorted(user_events, key=lambda e: e.ts):
            if current is None or ev.ts - current.end > SESSION_GAP:
                current = Session(user_id, ev.ts, ev.ts, [ev.page])
                sessions.append(current)
            else:
                current.end = ev.ts
                current.pages.append(ev.page)
        result[user_id] = sessions
    return result


def average_session_seconds(events):
    sessions = [s for user in sessionize(events).values() for s in user]
    if not sessions:
        return 0.0
    return sum(s.duration for s in sessions) / len(sessions)
