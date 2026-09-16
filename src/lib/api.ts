import { BACKEND_URL } from './socket';
import type { Difficulty, Problem, Track, TrackId } from './types';

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`);
  if (!res.ok) {
    throw new Error(`${path}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export function fetchTracks(): Promise<Track[]> {
  return getJson<Track[]>('/api/tracks');
}

export function fetchProblems(track?: TrackId, difficulty?: Difficulty): Promise<Problem[]> {
  const params = new URLSearchParams();
  if (track) {
    params.set('track', track);
  }
  if (difficulty) {
    params.set('difficulty', difficulty);
  }
  const qs = params.toString();
  return getJson<Problem[]>(`/api/problems${qs ? `?${qs}` : ''}`);
}

export function fetchProblem(id: string): Promise<Problem> {
  return getJson<Problem>(`/api/problems/${encodeURIComponent(id)}`);
}
