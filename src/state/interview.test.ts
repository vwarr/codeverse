import type { SessionInfo, TestRun } from '../lib/types';
import {
  formatClock,
  initialInterviewState,
  interviewReducer,
  isLive,
  secondsLeft,
  statusLine,
} from './interview';

const session: SessionInfo = {
  sessionId: 'abc',
  state: 'connecting',
  track: 'swe',
  surface: 'editor',
  languages: [],
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
};

describe('interviewReducer', () => {
  it('walks through a normal interview', () => {
    let s = interviewReducer(initialInterviewState, { type: 'start_requested' });
    expect(s.status).toBe('starting');
    s = interviewReducer(s, { type: 'started', session });
    expect(s.status).toBe('connecting');
    s = interviewReducer(s, { type: 'state', state: 'speaking' });
    s = interviewReducer(s, { type: 'transcript_delta', role: 'interviewer', text: 'Hel' });
    s = interviewReducer(s, { type: 'transcript_delta', role: 'interviewer', text: 'lo' });
    expect(s.live.interviewer).toBe('Hello');
    s = interviewReducer(s, {
      type: 'transcript_turn',
      turn: { role: 'interviewer', text: 'Hello', t: 1 },
    });
    expect(s.live.interviewer).toBe('');
    expect(s.transcript).toHaveLength(1);
    s = interviewReducer(s, { type: 'state', state: 'listening' });
    expect(isLive(s.status)).toBe(true);
    s = interviewReducer(s, {
      type: 'ended',
      metrics: {
        model_turns: 1,
        audio_in_seconds: 0,
        audio_out_seconds: 1,
        tool_calls: 0,
        response_latency_ms_p50: null,
        response_latency_ms_max: null,
      },
    });
    expect(s.status).toBe('ended');
    expect(isLive(s.status)).toBe(false);
  });

  it('interruption drops the partial interviewer line', () => {
    let s = interviewReducer(initialInterviewState, {
      type: 'transcript_delta',
      role: 'interviewer',
      text: 'partial',
    });
    s = interviewReducer(s, { type: 'interrupted' });
    expect(s.live.interviewer).toBe('');
  });

  it('reset keeps connection and mic state', () => {
    let s = interviewReducer(initialInterviewState, { type: 'connected', connected: true });
    s = interviewReducer(s, { type: 'mic', mic: 'on' });
    s = interviewReducer(s, { type: 'error', message: 'boom' });
    s = interviewReducer(s, { type: 'reset' });
    expect(s).toMatchObject({ status: 'idle', error: null, connected: true, mic: 'on' });
  });

  it('tracks debug test runs and ignores stale results', () => {
    const run = (n: number, passed: number): TestRun => ({
      run: n,
      ok: passed === 3,
      passed,
      total: 3,
      outcomes: [],
      stdout: '',
      stderr: '',
      load_error: null,
      timed_out: false,
      duration_ms: 10,
    });
    let s = interviewReducer(initialInterviewState, { type: 'run_requested' });
    expect(s.running).toBe(true);
    s = interviewReducer(s, { type: 'run_result', run: run(2, 3) });
    expect(s.running).toBe(false);
    expect(s.lastRun?.passed).toBe(3);
    s = interviewReducer(s, { type: 'run_result', run: run(1, 0) });
    expect(s.lastRun?.run).toBe(2);
    s = interviewReducer(s, { type: 'run_requested' });
    s = interviewReducer(s, { type: 'run_failed', error: 'Run limit reached' });
    expect(s.running).toBe(false);
    expect(s.runError).toBe('Run limit reached');
    expect(s.lastRun?.run).toBe(2);
    s = interviewReducer(s, { type: 'final_tests', result: run(0, 3) });
    expect(s.finalRun?.ok).toBe(true);
    s = interviewReducer(s, { type: 'start_requested' });
    expect(s.lastRun).toBeNull();
    expect(s.finalRun).toBeNull();
  });

  it('tracks reconnecting, mute and the interviewer wrap-up for the status line', () => {
    let s = interviewReducer(initialInterviewState, { type: 'start_requested' });
    s = interviewReducer(s, { type: 'started', session, at: 1000 });
    expect(statusLine(s)).toBe('Connecting to the interviewer…');
    s = interviewReducer(s, { type: 'state', state: 'listening' });
    s = interviewReducer(s, { type: 'mic', mic: 'on' });
    s = interviewReducer(s, { type: 'muted', muted: true });
    expect(statusLine(s)).toContain('muted');
    s = interviewReducer(s, { type: 'reconnecting', reconnecting: true });
    expect(statusLine(s)).toBe('Reconnecting to the interviewer…');
    s = interviewReducer(s, { type: 'reconnecting', reconnecting: false });
    s = interviewReducer(s, { type: 'state', state: 'wrapping_up', reason: 'interviewer' });
    expect(statusLine(s)).toBe('The interviewer is wrapping up');
    s = interviewReducer(s, { type: 'mic', mic: 'off' });
    expect(s.muted).toBe(false);
  });

  it('counts down the time left from maxSeconds', () => {
    let s = interviewReducer(initialInterviewState, {
      type: 'started',
      session: { ...session, maxSeconds: 600 },
      at: 10_000,
    });
    expect(secondsLeft(s, 10_000)).toBe(600);
    expect(secondsLeft(s, 10_000 + 61_000)).toBe(539);
    expect(secondsLeft(s, 10_000 + 700_000)).toBe(0);
    expect(formatClock(539)).toBe('8:59');
    s = interviewReducer(s, { type: 'reset' });
    expect(secondsLeft(s, 0)).toBeNull();
  });

  it('toggles mute, and a stopped microphone clears it', () => {
    let s = interviewReducer(initialInterviewState, { type: 'mic', mic: 'on' });
    expect(s.muted).toBe(false);
    s = interviewReducer(s, { type: 'muted', muted: true });
    expect(s.muted).toBe(true);
    s = interviewReducer(s, { type: 'muted', muted: false });
    expect(s.muted).toBe(false);
    s = interviewReducer(s, { type: 'muted', muted: true });
    s = interviewReducer(s, { type: 'mic', mic: 'off' });
    expect(s.muted).toBe(false);
  });
});
