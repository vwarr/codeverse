"""Persistence for the Vercel functions: interview sessions (per-IP limit, run counts) and reports.

`PostgresStore` talks to Neon through psycopg and creates its tables on first use. `MemoryStore`
is the same contract in a dict, for tests.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class SessionRow:
    id: str
    ip: str
    track: str
    problem_id: str
    language: str
    created_at: dt.datetime
    expires_at: dt.datetime
    ended_at: dt.datetime | None = None
    run_count: int = 0
    # Random ID from the browser's localStorage. It keys the History page, not the IP: a shared
    # IP (office, VPN) must not show other people's reports. None for old rows.
    client_id: str | None = None


class Store(Protocol):
    def active_sessions_for_ip(self, ip: str, now: dt.datetime) -> int:
        """Sessions whose token has not expired. A token cannot be revoked, so ending does not count."""

    def create_session(self, row: SessionRow) -> None: ...
    def get_session(self, session_id: str) -> SessionRow | None: ...
    def claim_run(self, session_id: str, max_runs: int) -> int | None:
        """Increment the run count if it is below max_runs. Return the new count, or None."""

    def end_session(self, session_id: str, now: dt.datetime) -> None: ...
    def get_report(self, session_id: str) -> dict[str, Any] | None: ...
    def list_reports(self, client_id: str, limit: int) -> list[dict[str, Any]]:
        """Complete reports for sessions started by `client_id`, newest first. Summary fields only:
        sessionId, track, problemId, createdAt, overallScore."""

    def save_report(self, session_id: str, record: dict[str, Any]) -> None:
        """Insert or replace the record, unless a complete report is already saved."""


class MemoryStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRow] = {}
        self.reports: dict[str, dict[str, Any]] = {}

    def active_sessions_for_ip(self, ip: str, now: dt.datetime) -> int:
        return sum(1 for s in self.sessions.values() if s.ip == ip and s.expires_at > now)

    def create_session(self, row: SessionRow) -> None:
        self.sessions[row.id] = row

    def get_session(self, session_id: str) -> SessionRow | None:
        return self.sessions.get(session_id)

    def claim_run(self, session_id: str, max_runs: int) -> int | None:
        row = self.sessions.get(session_id)
        if row is None or row.run_count >= max_runs:
            return None
        row.run_count += 1
        return row.run_count

    def end_session(self, session_id: str, now: dt.datetime) -> None:
        row = self.sessions.get(session_id)
        if row is not None and row.ended_at is None:
            row.ended_at = now

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        return self.reports.get(session_id)

    def list_reports(self, client_id: str, limit: int) -> list[dict[str, Any]]:
        rows = [
            _summary(sid, rec)
            for sid, rec in self.reports.items()
            if rec.get("status", "complete") == "complete"
            and (s := self.sessions.get(sid)) is not None
            and s.client_id is not None
            and s.client_id == client_id
        ]
        rows.sort(key=lambda r: r["createdAt"], reverse=True)
        return rows[:limit]

    def save_report(self, session_id: str, record: dict[str, Any]) -> None:
        current = self.reports.get(session_id)
        if current is None or current.get("status", "complete") != "complete":
            self.reports[session_id] = dict(record)


def _summary(session_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "track": record.get("track"),
        "problemId": record.get("problemId"),
        "createdAt": record.get("createdAt"),
        "overallScore": (record.get("report") or {}).get("overall_score"),
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS interview_sessions (
    id          text PRIMARY KEY,
    ip          text NOT NULL,
    track       text NOT NULL,
    problem_id  text NOT NULL,
    language    text NOT NULL,
    created_at  timestamptz NOT NULL,
    expires_at  timestamptz NOT NULL,
    ended_at    timestamptz,
    run_count   integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS interview_sessions_ip_idx ON interview_sessions (ip, expires_at);
CREATE TABLE IF NOT EXISTS interview_reports (
    session_id  text PRIMARY KEY REFERENCES interview_sessions (id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    record      jsonb NOT NULL
);
-- pending: transcript saved, report not written yet; failed: the text model failed; complete.
ALTER TABLE interview_reports ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'complete';
ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS client_id text;
CREATE INDEX IF NOT EXISTS interview_sessions_client_idx ON interview_sessions (client_id);
"""

_COLUMNS = "id, ip, track, problem_id, language, created_at, expires_at, ended_at, run_count, client_id"


class PostgresStore:
    """One short-lived connection per call: functions are stateless and Neon pools on its side."""

    _schema_ready = False

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> Any:
        import psycopg  # imported lazily so the tests don't need it

        if not self._dsn:
            raise RuntimeError("DATABASE_URL is not set")

        conn = psycopg.connect(self._dsn, autocommit=True, connect_timeout=10)
        if not PostgresStore._schema_ready:
            conn.execute(SCHEMA)
            PostgresStore._schema_ready = True
        return conn

    def active_sessions_for_ip(self, ip: str, now: dt.datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM interview_sessions WHERE ip = %s AND expires_at > %s",
                (ip, now),
            ).fetchone()
        return int(row[0])

    def create_session(self, row: SessionRow) -> None:
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO interview_sessions ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    row.id,
                    row.ip,
                    row.track,
                    row.problem_id,
                    row.language,
                    row.created_at,
                    row.expires_at,
                    row.ended_at,
                    row.run_count,
                    row.client_id,
                ),
            )

    def get_session(self, session_id: str) -> SessionRow | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM interview_sessions WHERE id = %s", (session_id,)
            ).fetchone()
        return SessionRow(*row) if row else None

    def claim_run(self, session_id: str, max_runs: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE interview_sessions SET run_count = run_count + 1 "
                "WHERE id = %s AND run_count < %s RETURNING run_count",
                (session_id, max_runs),
            ).fetchone()
        return int(row[0]) if row else None

    def end_session(self, session_id: str, now: dt.datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE interview_sessions SET ended_at = %s WHERE id = %s AND ended_at IS NULL",
                (now, session_id),
            )

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record FROM interview_reports WHERE session_id = %s", (session_id,)
            ).fetchone()
        if not row:
            return None
        return row[0] if isinstance(row[0], dict) else json.loads(row[0])

    def list_reports(self, client_id: str, limit: int) -> list[dict[str, Any]]:
        # Only the summary fields leave the database, not transcripts or code.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT r.session_id, r.record->>'track', r.record->>'problemId', "
                "r.record->>'createdAt', (r.record->'report'->>'overall_score')::int "
                "FROM interview_reports r JOIN interview_sessions s ON s.id = r.session_id "
                "WHERE s.client_id = %s AND r.status = 'complete' "
                "ORDER BY r.created_at DESC LIMIT %s",
                (client_id, limit),
            ).fetchall()
        keys = ("sessionId", "track", "problemId", "createdAt", "overallScore")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def save_report(self, session_id: str, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO interview_reports (session_id, status, record) VALUES (%s, %s, %s) "
                "ON CONFLICT (session_id) DO UPDATE SET status = EXCLUDED.status, record = EXCLUDED.record, "
                "created_at = now() WHERE interview_reports.status <> 'complete'",
                (session_id, record.get("status", "complete"), json.dumps(record)),
            )
