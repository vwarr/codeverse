import type { InterviewApi } from '../api';
import type { ReportRequest, SessionGrant, SessionInfo, TestRun } from '../types';
import type { LiveCallbacks, LiveConnection, LiveConnectOptions, LiveMessage } from './connector';
import { arrayBufferToBase64, base64ToArrayBuffer, LiveInterview } from './LiveInterview';

const session: SessionInfo = {
  sessionId: 's1',
  state: 'connecting',
  track: 'debug',
  surface: 'editor',
  languages: ['python'],
  canRun: true,
  language: 'python',
  inputSampleRate: 16000,
  outputSampleRate: 24000,
  promptVersion: 'test',
  problem: {
    id: 'cart',
    track: 'debug',
    title: 'Cart',
    difficulty: 'easy',
    tags: [],
    statement: 'x',
    examples: [],
    constraints: [],
    starter_code: {},
  },
};

const grant: SessionGrant = {
  ok: true,
  token: 'auth_tokens/t1',
  apiVersion: 'v1alpha',
  model: 'live-model',
  maxSeconds: 600,
  expiresAt: '2026-11-03T12:13:00Z',
  codeDebounceSeconds: 1,
  openingInstruction: 'OPEN',
  wrapUpInstruction: 'WRAP',
  session,
};

const run: TestRun = {
  run: 1,
  ok: false,
  passed: 1,
  total: 2,
  outcomes: [],
  stdout: '',
  stderr: '',
  load_error: null,
  timed_out: false,
  duration_ms: 5,
};

class FakeConn implements LiveConnection {
  audio: string[] = [];
  texts: { text: string; turnComplete: boolean }[] = [];
  toolResponses: { id: string; name: string; response: Record<string, unknown> }[] = [];
  closed = false;
  opts: LiveConnectOptions;
  cb: LiveCallbacks;
  constructor(opts: LiveConnectOptions, cb: LiveCallbacks) {
    this.opts = opts;
    this.cb = cb;
  }
  sendAudio = (data: string) => void this.audio.push(data);
  sendText = (text: string, turnComplete: boolean) => void this.texts.push({ text, turnComplete });
  sendToolResponse = (r: FakeConn['toolResponses']) => void this.toolResponses.push(...r);
  close = () => {
    this.closed = true;
  };
  msg(m: LiveMessage) {
    this.cb.onMessage(m);
  }
}

function setup() {
  let now = 100;
  const conns: FakeConn[] = [];
  const reports: ReportRequest[] = [];
  const api: InterviewApi = {
    createSession: vi.fn(async () => grant),
    runTests: vi.fn(async () => ({
      ok: true as const,
      result: run,
      summary: '1 of 2 tests passed.',
    })),
    endSession: vi.fn(),
    createReport: vi.fn(async (req: ReportRequest) => {
      reports.push(req);
      return {
        ok: true as const,
        report: { overall_score: 3 } as never,
        finalRun: { ...run, passed: 2, ok: true },
      };
    }),
  };
  const live = new LiveInterview({
    api,
    connect: async (opts, cb) => {
      const c = new FakeConn(opts, cb);
      conns.push(c);
      return c;
    },
    clock: () => now,
  });
  const events: [string, any][] = [];
  for (const e of [
    'interview_started',
    'session_state',
    'audio_out',
    'transcript_delta',
    'transcript_turn',
    'interrupted',
    'tool_call',
    'run_result',
    'final_tests',
    'feedback',
    'interview_ended',
    'connection',
    'error',
  ]) {
    live.on(e, (d: unknown) => events.push([e, d]));
  }
  const states = () => events.filter(([e]) => e === 'session_state').map(([, d]) => d.state);
  const tick = (s: number) => {
    now += s;
  };
  return { live, api, conns, reports, events, states, tick };
}

const audio = (bytes: number): LiveMessage => ({
  serverContent: {
    modelTurn: { parts: [{ inlineData: { data: arrayBufferToBase64(new ArrayBuffer(bytes)) } }] },
  },
});

afterEach(() => {
  vi.useRealTimers();
});

describe('LiveInterview', () => {
  it('connects with the token and opens the interview', async () => {
    const { live, conns, states } = setup();
    const ack = await live.start({ track: 'debug' });
    expect(ack).toEqual({ ok: true, session: { ...session, maxSeconds: 600 } });
    expect(conns).toHaveLength(1);
    expect(conns[0].opts).toEqual({
      token: 'auth_tokens/t1',
      apiVersion: 'v1alpha',
      model: 'live-model',
      handle: null,
    });
    expect(conns[0].texts).toEqual([{ text: 'OPEN', turnComplete: true }]);
    expect(states()).toEqual(['connecting', 'thinking']);
  });

  it('reports a failed session request', async () => {
    const { live, api, conns } = setup();
    vi.mocked(api.createSession).mockResolvedValueOnce({ ok: false, error: 'Too many' });
    expect(await live.start({ track: 'swe' })).toEqual({ ok: false, error: 'Too many' });
    expect(conns).toHaveLength(0);
  });

  it('streams audio both ways, builds the transcript and measures latency', async () => {
    const { live, conns, events, states, tick } = setup();
    await live.start({ track: 'debug' });
    const c = conns[0];

    c.msg(audio(4800));
    c.msg({ serverContent: { outputTranscription: { text: 'Hello there.' } } });
    c.msg({ serverContent: { turnComplete: true } });
    expect(states()).toEqual(['connecting', 'thinking', 'speaking', 'listening']);

    live.emit('audio_in', new Int16Array([1, 2, 3]).buffer);
    expect(c.audio).toHaveLength(1);
    expect(new Int16Array(base64ToArrayBuffer(c.audio[0]))).toEqual(new Int16Array([1, 2, 3]));

    c.msg({ serverContent: { inputTranscription: { text: 'I would ' } } });
    c.msg({ serverContent: { inputTranscription: { text: 'run the tests.' } } });
    tick(0.42);
    c.msg(audio(9600));
    c.msg({ serverContent: { turnComplete: true } });

    const turns = events.filter(([e]) => e === 'transcript_turn').map(([, d]) => d);
    expect(turns.map((t) => [t.role, t.text])).toEqual([
      ['interviewer', 'Hello there.'],
      ['candidate', 'I would run the tests.'],
    ]);
    const out = events.filter(([e]) => e === 'audio_out').map(([, d]) => d.byteLength);
    expect(out).toEqual([4800, 9600]);
    const m = live.metrics();
    expect(m.model_turns).toBe(2);
    expect(m.response_latency_ms_p50).toBe(420); // the first turn has no candidate speech
    expect(m.audio_out_seconds).toBe(0.3);
  });

  it('drops a barged-in turn and goes back to listening', async () => {
    const { live, conns, events, states } = setup();
    await live.start({ track: 'debug' });
    conns[0].msg(audio(10));
    conns[0].msg({ serverContent: { interrupted: true } });
    expect(events.some(([e]) => e === 'interrupted')).toBe(true);
    expect(states().at(-1)).toBe('listening');
  });

  it('answers tool calls from browser state', async () => {
    const { live, conns } = setup();
    await live.start({ track: 'debug' });
    const c = conns[0];
    live.emit('code_update', { code: 'def f():\n    return 1\n', language: 'python' });
    c.msg({ toolCall: { functionCalls: [{ id: 'a', name: 'get_current_code' }] } });
    c.msg({ toolCall: { functionCalls: [{ id: 'b', name: 'get_last_test_run' }] } });

    let ack: unknown;
    live.emit('run_tests', { code: 'fixed' }, (r) => {
      ack = r;
    });
    await vi.waitFor(() => expect(ack).toEqual({ ok: true, result: run }));
    c.msg({ toolCall: { functionCalls: [{ id: 'c', name: 'get_last_test_run' }] } });
    c.msg({ toolCall: { functionCalls: [{ id: 'd', name: 'nope' }] } });

    expect(c.toolResponses.map((r) => [r.id, r.response])).toEqual([
      ['a', { language: 'python', code: 'def f():\n    return 1', line_count: 2 }],
      ['b', { ran: false, note: 'The candidate has not run the tests yet.' }],
      [
        'c',
        {
          ran: true,
          runs_so_far: 1,
          seconds_ago: 0,
          code_changed_since: false,
          summary: '1 of 2 tests passed.',
        },
      ],
      ['d', { error: "unknown tool 'nope'" }],
    ]);
    // The run result also goes into the model's context, without asking for a turn.
    expect(c.texts.at(-1)?.turnComplete).toBe(false);
    expect(c.texts.at(-1)?.text).toContain('1 of 2 tests passed.');
  });

  it('pushes debounced code snapshots as context', async () => {
    vi.useFakeTimers();
    const { live, conns } = setup();
    await live.start({ track: 'debug' });
    live.emit('code_update', { code: 'a' });
    live.emit('code_update', { code: 'ab' });
    vi.advanceTimersByTime(1000);
    const ctx = conns[0].texts.filter((t) => !t.turnComplete);
    expect(ctx).toHaveLength(1);
    expect(ctx[0].text).toContain('\nab');
  });

  it('wraps up via the tool, then ends and fetches the report', async () => {
    const { live, conns, events, reports, states } = setup();
    await live.start({ track: 'debug' });
    const c = conns[0];
    live.emit('code_update', { code: 'final code' });
    c.msg({ serverContent: { inputTranscription: { text: 'I am done.' } } });
    c.msg({ toolCall: { functionCalls: [{ id: 'w', name: 'request_wrap_up' }] } });
    expect(c.toolResponses[0].response).toEqual({ ok: true, instruction: 'WRAP' });
    // No extra wrap-up turn: the instruction travels in the tool result.
    expect(c.texts.filter((t) => t.text === 'WRAP')).toHaveLength(0);
    c.msg(audio(100));
    c.msg({ serverContent: { outputTranscription: { text: 'Thanks, goodbye.' } } });
    c.msg({ serverContent: { turnComplete: true } });

    await vi.waitFor(() => expect(events.some(([e]) => e === 'interview_ended')).toBe(true));
    expect(states().slice(-2)).toEqual(['wrapping_up', 'ended']);
    expect(c.closed).toBe(true);
    expect(reports).toHaveLength(1);
    expect(reports[0].code).toBe('final code');
    expect(reports[0].transcript.map((t) => t.text)).toEqual(['I am done.', 'Thanks, goodbye.']);
    const names = events.map(([e]) => e);
    expect(names.indexOf('final_tests')).toBeLessThan(names.indexOf('feedback'));
    expect(names.indexOf('feedback')).toBeLessThan(names.indexOf('interview_ended'));
  });

  it('Finish sends the wrap-up instruction as a user turn', async () => {
    const { live, conns, events } = setup();
    await live.start({ track: 'debug' });
    let acked = false;
    live.emit('end_interview', {}, () => {
      acked = true;
    });
    expect(conns[0].texts.at(-1)).toEqual({ text: 'WRAP', turnComplete: true });
    conns[0].msg({ serverContent: { turnComplete: true } });
    await vi.waitFor(() => expect(acked).toBe(true));
    expect(events.some(([e]) => e === 'feedback')).toBe(true);
  });

  it('wraps up when the time limit is reached', async () => {
    vi.useFakeTimers();
    const { live, conns, states } = setup();
    await live.start({ track: 'debug' });
    vi.advanceTimersByTime(600_000);
    expect(states().at(-1)).toBe('wrapping_up');
    expect(conns[0].texts.at(-1)).toEqual({ text: 'WRAP', turnComplete: true });
  });

  it('resumes with the latest handle when the connection closes', async () => {
    const { live, conns, states } = setup();
    await live.start({ track: 'debug' });
    conns[0].msg({ sessionResumptionUpdate: { resumable: true, newHandle: 'h1' } });
    conns[0].msg({ goAway: { timeLeft: '5s' } });
    conns[0].cb.onClose('going away');
    await vi.waitFor(() => expect(conns).toHaveLength(2));
    expect(conns[1].opts.handle).toBe('h1');
    expect(conns[1].opts.token).toBe('auth_tokens/t1');
    live.emit('audio_in', new ArrayBuffer(4));
    expect(conns[1].audio).toHaveLength(1);
    expect(states()).not.toContain('error');
  });

  it('reports reconnecting while it resumes the connection', async () => {
    const { live, conns, events } = setup();
    await live.start({ track: 'debug' });
    conns[0].msg({ sessionResumptionUpdate: { resumable: true, newHandle: 'h1' } });
    conns[0].cb.onClose('going away');
    const flags = () => events.filter(([e]) => e === 'connection').map(([, d]) => d.reconnecting);
    await vi.waitFor(() => expect(flags()).toEqual([true, false]));
    expect(conns).toHaveLength(2);
    expect(live.snapshot().state).not.toBe('error');
  });

  it('fails when the connection closes with no handle', async () => {
    const { live, conns, events } = setup();
    await live.start({ track: 'debug' });
    conns[0].cb.onClose('boom');
    await vi.waitFor(() => expect(events.some(([e]) => e === 'error')).toBe(true));
    expect(events.find(([e]) => e === 'error')?.[1].message).toContain('boom');
  });

  it('ends the session on the server when it fails, since no report will follow', async () => {
    const { live, api, conns, events } = setup();
    await live.start({ track: 'debug' });
    conns[0].cb.onClose('boom');
    await vi.waitFor(() => expect(events.some(([e]) => e === 'error')).toBe(true));
    expect(api.endSession).toHaveBeenCalledTimes(1);
    expect(api.endSession).toHaveBeenCalledWith('s1');
    expect(api.createReport).not.toHaveBeenCalled();
    // Closing the tab afterwards sends nothing more.
    window.dispatchEvent(new Event('pagehide'));
    expect(api.endSession).toHaveBeenCalledTimes(1);
  });

  it('sends an end beacon if the tab closes during the interview', async () => {
    const { live, api } = setup();
    await live.start({ track: 'debug' });
    window.dispatchEvent(new Event('pagehide'));
    expect(api.endSession).toHaveBeenCalledWith('s1', { beacon: true });
  });

  it('sends no end beacon once the report is requested', async () => {
    const { live, api, conns, events } = setup();
    await live.start({ track: 'debug' });
    live.emit('end_interview', {});
    conns[0].msg({ serverContent: { turnComplete: true } });
    await vi.waitFor(() => expect(events.some(([e]) => e === 'interview_ended')).toBe(true));
    expect(api.createReport).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event('pagehide'));
    expect(api.endSession).not.toHaveBeenCalled();
  });

  it('fails cleanly when the first connection is refused', async () => {
    const api = {
      createSession: vi.fn(async () => grant),
      runTests: vi.fn(),
      createReport: vi.fn(),
      endSession: vi.fn(),
    } as unknown as InterviewApi;
    const live = new LiveInterview({
      api,
      connect: async () => {
        throw new Error('token expired');
      },
    });
    const errors: string[] = [];
    live.on('error', (d: { message: string }) => errors.push(d.message));
    expect((await live.start({ track: 'swe' })).ok).toBe(true);
    expect(errors[0]).toContain('token expired');
    expect(api.endSession).toHaveBeenCalledWith('s1');
    expect(api.createReport).not.toHaveBeenCalled();
  });

  it('refuses test runs when the track cannot run code', async () => {
    const { live, api } = setup();
    vi.mocked(api.createSession).mockResolvedValueOnce({
      ...grant,
      session: { ...session, canRun: false },
    });
    await live.start({ track: 'swe' });
    expect((await live.runTests('x')).ok).toBe(false);
    expect(api.runTests).not.toHaveBeenCalled();
  });
});
