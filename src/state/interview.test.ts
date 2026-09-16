import type { SessionInfo } from '../lib/types';
import { initialInterviewState, interviewReducer, isLive } from './interview';

const session: SessionInfo = {
  sessionId: 'abc',
  state: 'connecting',
  track: 'swe',
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
});
