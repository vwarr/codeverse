// Demo mode keeps saved reports in localStorage, so the History page has something to show.

import type { HistoryItem, Problem, ReportRecord } from '../types';

const KEY = 'codeverse.demo.reports';
const MAX = 20;

function load(): ReportRecord[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ReportRecord[]) : [];
  } catch {
    return [];
  }
}

export function saveDemoReport(record: ReportRecord): void {
  try {
    const rest = load().filter((r) => r.sessionId !== record.sessionId);
    window.localStorage.setItem(KEY, JSON.stringify([record, ...rest].slice(0, MAX)));
  } catch {
    // Storage full or blocked: the demo works without history.
  }
}

export function demoReport(sessionId: string): ReportRecord | null {
  return load().find((r) => r.sessionId === sessionId) ?? null;
}

export function demoHistory(problems: Problem[]): HistoryItem[] {
  return load().map((r) => {
    const p = problems.find((x) => x.id === r.problemId);
    return {
      sessionId: r.sessionId,
      track: r.track,
      problemId: r.problemId,
      problemTitle: p?.title ?? r.problemId,
      difficulty: p?.difficulty ?? null,
      createdAt: r.createdAt,
      overallScore: r.report?.overall_score ?? 0,
    };
  });
}
