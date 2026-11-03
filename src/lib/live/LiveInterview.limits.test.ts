// Rate limits and dropped connections: the interview ends cleanly and the transcript still goes to
// /api/report.

import type { InterviewApi } from '../api';
import type { ReportRequest, SessionGrant } from '../types';
import type { LiveCallbacks, LiveConnection } from './connector';
import { isRateLimited, LiveInterview } from './LiveInterview';

const grant = {
  ok: true,
  token: 'auth_tokens/t1',
  apiVersion: 'v1beta',
  model: 'live-model',
  maxSeconds: 600,
  expiresAt: '2026-11-03T12:13:00Z',
  codeDebounceSeconds: 1,
  openingInstruction: 'OPEN',
  wrapUpInstruction: 'WRAP',
  session: {
    sessionId: 's1',
    state: 'connecting',
    track: 'swe',
    surface: 'editor',
    languages: ['python'],
    canRun: false,
    language: 'python',
    inputSampleRate: 16000,
    outputSampleRate: 24000,
    promptVersion: 'test',
    problem: {
      id: 'two-sum',
      track: 'swe',
      title: 'Two Sum',
      difficulty: 'easy',
      tags: [],
      statement: 'x',
      examples: [],
      constraints: [],
      starter_code: {},
    },
  },
} as unknown as SessionGrant;

function setup(reportResults: Awaited<ReturnType<InterviewApi['createReport']>>[] = []) {
  const callbacks: LiveCallbacks[] = [];
  const reports: ReportRequest[] = [];
  const api: InterviewApi = {
    createSession: vi.fn(async () => grant),
    runTests: vi.fn(),
    createReport: vi.fn(async (req: ReportRequest) => {
      reports.push(req);
      return (
        reportResults.shift() ?? {
          ok: true as const,
          report: { overall_score: 3 } as never,
          finalRun: null,
        }
      );
    }),
  };
  const live = new LiveInterview({
    api,
    connect: async (_opts, cb) => {
      callbacks.push(cb);
      const conn: LiveConnection = {
        sendAudio: () => {},
        sendText: () => {},
        sendToolResponse: () => {},
        close: () => {},
      };
      return conn;
    },
  });
  const events: [string, any][] = [];
  for (const e of ['session_state', 'error', 'feedback', 'interview_ended']) {
    live.on(e, (d: unknown) => events.push([e, d]));
  }
  return { live, callbacks, reports, events, api };
}

describe('LiveInterview rate limits', () => {
  it('recognises rate-limit and quota errors', () => {
    expect(isRateLimited('429 RESOURCE_EXHAUSTED')).toBe(true);
    expect(isRateLimited('You exceeded your current quota')).toBe(true);
    expect(isRateLimited('normal closure')).toBe(false);
  });

  it('ends cleanly on a quota drop, without reconnecting, and still asks for the report', async () => {
    const { live, callbacks, reports, events } = setup();
    await live.start({ track: 'swe' });
    callbacks[0].onMessage({ sessionResumptionUpdate: { resumable: true, newHandle: 'h1' } });
    callbacks[0].onMessage({ serverContent: { inputTranscription: { text: 'My approach is' } } });
    callbacks[0].onClose('RESOURCE_EXHAUSTED: quota exceeded');
    await vi.waitFor(() => expect(events.some(([e]) => e === 'interview_ended')).toBe(true));

    expect(callbacks).toHaveLength(1); // no reconnect on a quota error
    expect(events.find(([e, d]) => e === 'session_state' && d.state === 'ended')?.[1].reason).toBe(
      'quota'
    );
    expect(events.some(([e]) => e === 'error')).toBe(false);
    expect(reports[0].endReason).toBe('quota');
    expect(reports[0].transcript.map((t) => t.text)).toEqual(['My approach is']);
    expect(events.some(([e]) => e === 'feedback')).toBe(true);
  });

  it('ends cleanly when the connection is lost after the interview started', async () => {
    const { live, callbacks, reports } = setup();
    await live.start({ track: 'swe' });
    callbacks[0].onMessage({ serverContent: { outputTranscription: { text: 'Hello.' } } });
    callbacks[0].onMessage({ serverContent: { turnComplete: true } });
    callbacks[0].onClose('network error');
    await vi.waitFor(() => expect(reports).toHaveLength(1));
    expect(reports[0].endReason).toBe('connection_lost');
  });

  it('fails with a clear message when the first connection hits a rate limit', async () => {
    const { live, events, reports } = setup();
    vi.spyOn(live as any, 'connector').mockRejectedValueOnce(new Error('429 Too Many Requests'));
    await live.start({ track: 'swe' });
    expect(events.find(([e]) => e === 'error')?.[1].message).toMatch(/usage limit/);
    expect(reports).toHaveLength(0);
  });

  it('retries the report once if the request never reached the server', async () => {
    vi.useFakeTimers();
    try {
      const { live, callbacks, reports, events } = setup([
        { ok: false, error: 'Could not reach the server: Failed to fetch' },
      ]);
      await live.start({ track: 'swe' });
      callbacks[0].onMessage({ serverContent: { inputTranscription: { text: 'hi' } } });
      live.emit('end_interview', {});
      callbacks[0].onMessage({ serverContent: { turnComplete: true } });
      await vi.advanceTimersByTimeAsync(5000);
      expect(reports).toHaveLength(2);
      expect(events.some(([e]) => e === 'feedback')).toBe(true);
      expect(events.some(([e]) => e === 'error')).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
