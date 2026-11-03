// The app's own API: Vercel functions on the same origin (see api/ at the repo root). The app is served
// under Vite's base (/codeverse/), and vercel.json rewrites /codeverse/api/* to the functions.

import { clientId } from './clientId';
import { DEMO_PROBLEMS, DEMO_TRACKS } from './demo/demoSocket';
import { demoHistory, demoReport } from './demo/history';
import { DEMO } from './env';
import type {
  Difficulty,
  HistoryItem,
  Problem,
  ReportRecord,
  ReportRequest,
  ReportResponse,
  RunResponse,
  SessionGrant,
  StartRequest,
  Track,
  TrackId,
} from './types';

/** The URL of an API route, e.g. apiUrl('session') is /codeverse/api/session. */
export function apiUrl(route: string): string {
  return `${import.meta.env.BASE_URL}api/${route}`;
}

async function getJson<T>(path: string, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(path, headers ? { headers } : undefined);
  if (!res.ok) {
    throw new Error(`${path}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const UNREACHABLE = 'Could not reach the server';

/** POST JSON. Errors come back as { ok: false, error } instead of throwing. */
async function postJson<T>(path: string, body: unknown): Promise<T | { ok: false; error: string }> {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = (await res.json().catch(() => null)) as T | { error?: string } | null;
    if (!res.ok || !data) {
      const error = (data as { error?: string } | null)?.error;
      return { ok: false, error: error ?? `${path}: ${res.status} ${res.statusText}` };
    }
    return data as T;
  } catch (e) {
    return { ok: false, error: `${UNREACHABLE}: ${(e as Error).message}` };
  }
}

export function fetchTracks(): Promise<Track[]> {
  if (DEMO) {
    return Promise.resolve(DEMO_TRACKS);
  }
  return getJson<Track[]>(apiUrl('tracks'));
}

export function fetchProblems(track?: TrackId, difficulty?: Difficulty): Promise<Problem[]> {
  if (DEMO) {
    return Promise.resolve(
      DEMO_PROBLEMS.filter(
        (p) => (!track || p.track === track) && (!difficulty || p.difficulty === difficulty)
      )
    );
  }
  const params = new URLSearchParams();
  if (track) {
    params.set('track', track);
  }
  if (difficulty) {
    params.set('difficulty', difficulty);
  }
  const qs = params.toString();
  return getJson<Problem[]>(`${apiUrl('problems')}${qs ? `?${qs}` : ''}`);
}

export function fetchProblem(id: string): Promise<Problem> {
  const demo = DEMO ? DEMO_PROBLEMS.find((p) => p.id === id) : undefined;
  if (demo) {
    return Promise.resolve(demo);
  }
  return getJson<Problem>(`${apiUrl('problems')}?id=${encodeURIComponent(id)}`);
}

/** A saved report (the History page links here). */
export function fetchReport(sessionId: string): Promise<ReportRecord> {
  if (DEMO) {
    const record = demoReport(sessionId);
    return record ? Promise.resolve(record) : Promise.reject(new Error('report not found'));
  }
  return getJson<ReportRecord>(`${apiUrl('report')}?sessionId=${encodeURIComponent(sessionId)}`);
}

/** Saved reports for this browser (its client ID; there are no accounts), newest first. */
export async function fetchHistory(): Promise<HistoryItem[]> {
  if (DEMO) {
    return demoHistory(DEMO_PROBLEMS);
  }
  const data = await getJson<{ ok: boolean; reports: HistoryItem[] }>(apiUrl('history'), {
    'X-Client-Id': clientId(),
  });
  return data.reports;
}

/** The calls LiveInterview makes. An interface so tests can pass a fake. */
export interface InterviewApi {
  createSession: (req: StartRequest) => Promise<SessionGrant | { ok: false; error: string }>;
  runTests: (sessionId: string, code: string) => Promise<RunResponse>;
  createReport: (req: ReportRequest) => Promise<ReportResponse>;
}

export const httpApi: InterviewApi = {
  createSession: (req) =>
    postJson<SessionGrant>(apiUrl('session'), { ...req, clientId: clientId() }),
  runTests: (sessionId, code) => postJson<RunResponse>(apiUrl('run_tests'), { sessionId, code }),
  createReport: (req) => postJson<ReportResponse>(apiUrl('report'), req),
};
