import type { InterviewApi } from '../api';
import type { ReportRequest, SessionGrant, SessionInfo, TestRun } from '../types';
import type { LiveCallbacks, LiveConnection, LiveConnectOptions, LiveMessage } from './connector';
import {
  arrayBufferToBase64,
  base64ToArrayBuffer,
  LiveInterview,
  timeNote,
  timeNoteSchedule,
} from './LiveInterview';

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
    'transcript',
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

    const turns = events.filter(([e]) => e === 'transcript').at(-1)![1].turns as any[];
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

// Event sequences in the shapes of BidiGenerateContentServerContent
// (https://aistudio.google.com/api-reference/live): `inputTranscription` is sent independently of
// the other messages, with no guaranteed ordering; the last `outputTranscription` of a turn comes
// before `generationComplete` (or `interrupted`), and `turnComplete` follows.
describe('LiveInterview transcript order', () => {
  const said = (text: string, finished?: boolean): LiveMessage => ({
    serverContent: { inputTranscription: finished ? { text, finished } : { text } },
  });
  const says = (text: string): LiveMessage => ({
    serverContent: { outputTranscription: { text } },
  });
  const generationComplete: LiveMessage = { serverContent: { generationComplete: true } };
  const turnComplete: LiveMessage = { serverContent: { turnComplete: true } };

  async function started() {
    const ctx = setup();
    await ctx.live.start({ track: 'debug' });
    const c = ctx.conns[0];
    const lines = () => {
      const last = ctx.events.filter(([e]) => e === 'transcript').at(-1);
      return ((last?.[1].turns ?? []) as { role: string; text: string }[]).map((t) => [
        t.role[0].toUpperCase(),
        t.text,
      ]);
    };
    // The opening: the model speaks first, in answer to the hidden opening instruction.
    const opening = () => {
      c.msg(audio(480));
      c.msg(says('Hi, I am '));
      c.msg(says('your interviewer.'));
      c.msg(generationComplete);
      c.msg(turnComplete);
      ctx.tick(3);
    };
    return { ...ctx, c, lines, opening };
  }

  it('puts the opening first and never shows the hidden instructions', async () => {
    const { live, c, lines, reports, events } = await started();
    c.msg(audio(480));
    c.msg(says('Hi, I am '));
    // The candidate talks over the greeting without a barge-in.
    c.msg(said('Hello.'));
    c.msg(says('your interviewer.'));
    c.msg(generationComplete);
    c.msg(turnComplete);
    expect(lines()).toEqual([
      ['I', 'Hi, I am your interviewer.'],
      ['C', 'Hello.'],
    ]);

    live.emit('end_interview', {});
    expect(c.texts.map((t) => t.text)).toEqual(['OPEN', 'WRAP']);
    c.msg(audio(480));
    c.msg(says('Thanks for your time.'));
    c.msg(turnComplete);
    await vi.waitFor(() => expect(events.some(([e]) => e === 'interview_ended')).toBe(true));
    const texts = reports[0].transcript.map((t) => t.text);
    expect(texts).toEqual(['Hi, I am your interviewer.', 'Hello.', 'Thanks for your time.']);
    expect(texts.join(' ')).not.toMatch(/OPEN|WRAP/);
  });

  it('keeps the candidate before the reply when their words arrive after it started', async () => {
    const { c, lines, opening, states } = await started();
    opening();
    c.msg(said('I think the'));
    c.msg(audio(4800));
    c.msg(says('Good'));
    c.msg(said(' bug is in the loop.'));
    c.msg(says(' point.'));
    c.msg(generationComplete);
    c.msg(said(' Probably off by one.'));
    c.msg(turnComplete);
    expect(lines()).toEqual([
      ['I', 'Hi, I am your interviewer.'],
      ['C', 'I think the bug is in the loop. Probably off by one.'],
      ['I', 'Good point.'],
    ]);
    expect(states().at(-1)).toBe('listening');
  });

  it('puts words that arrive only after the reply is complete before the reply', async () => {
    const { c, lines, opening, tick, states, live } = await started();
    opening();
    // The candidate's speech made the model answer; its transcription comes last.
    c.msg(audio(4800));
    c.msg(says('Sure, go ahead.'));
    c.msg(generationComplete);
    c.msg(turnComplete);
    tick(0.4);
    c.msg(said('Can I use '));
    c.msg(said('a hash map?'));
    expect(lines()).toEqual([
      ['I', 'Hi, I am your interviewer.'],
      ['C', 'Can I use a hash map?'],
      ['I', 'Sure, go ahead.'],
    ]);
    // Late words of an answered turn do not change the state.
    expect(states().at(-1)).toBe('listening');
    const t = live.snapshot().transcript.map((x) => x.t);
    expect([...t].sort((a, b) => a - b)).toEqual(t);
  });

  it('ends the reply on a barge-in and starts a new candidate turn', async () => {
    const { c, lines, opening, events } = await started();
    opening();
    c.msg(said('What is the complexity?'));
    c.msg(audio(4800));
    c.msg(says('It is linear, because the'));
    c.msg({ serverContent: { interrupted: true, inputTranscription: { text: 'Wait,' } } });
    expect(events.some(([e]) => e === 'interrupted')).toBe(true);
    c.msg(turnComplete);
    c.msg(said(' sorry, I meant space.'));
    c.msg(audio(4800));
    c.msg(says('Space is constant.'));
    c.msg(generationComplete);
    c.msg(turnComplete);
    expect(lines()).toEqual([
      ['I', 'Hi, I am your interviewer.'],
      ['C', 'What is the complexity?'],
      ['I', 'It is linear, because the'],
      ['C', 'Wait, sorry, I meant space.'],
      ['I', 'Space is constant.'],
    ]);
  });

  it('keeps one interviewer line across a tool call in the middle of a turn', async () => {
    const { live, c, lines, opening } = await started();
    opening();
    live.emit('code_update', { code: 'for i in range(n - 1):' });
    c.msg(said('Can you look at my code?'));
    c.msg(audio(4800));
    c.msg(says('Let me look.'));
    c.msg({ toolCall: { functionCalls: [{ id: 'c1', name: 'get_current_code' }] } });
    expect(c.toolResponses).toHaveLength(1);
    // Some sessions end the turn at the tool call and continue after the tool response.
    c.msg(turnComplete);
    c.msg(said(' Thanks.'));
    c.msg(audio(4800));
    c.msg(says('Your loop'));
    c.msg(says(' stops one early.'));
    c.msg(generationComplete);
    c.msg(turnComplete);
    expect(lines()).toEqual([
      ['I', 'Hi, I am your interviewer.'],
      ['C', 'Can you look at my code? Thanks.'],
      ['I', 'Let me look. Your loop stops one early.'],
    ]);
  });

  it('keeps two quick candidate turns apart and in order', async () => {
    const { c, lines, opening, tick } = await started();
    opening();
    c.msg(said('I will use two pointers.', true));
    c.msg(audio(2400));
    c.msg(says('Okay.'));
    c.msg(generationComplete);
    c.msg(turnComplete);
    tick(2);
    // The second reply starts before the second turn's words arrive.
    c.msg(audio(2400));
    c.msg(says('Go on.'));
    c.msg(said('Then I move'));
    c.msg(said(' the left one.'));
    c.msg(generationComplete);
    c.msg(turnComplete);
    tick(2);
    c.msg(said('Done.'));
    expect(lines()).toEqual([
      ['I', 'Hi, I am your interviewer.'],
      ['C', 'I will use two pointers.'],
      ['I', 'Okay.'],
      ['C', 'Then I move the left one.'],
      ['I', 'Go on.'],
      ['C', 'Done.'],
    ]);
  });

  it('waits for the reply to play before late words become a new turn', async () => {
    const { c, lines, opening, tick } = await started();
    opening();
    // Five seconds of audio (24 kHz, 16-bit) arrive at once; turnComplete comes before playback ends.
    c.msg(audio(5 * 48000));
    c.msg(says('That is a long answer.'));
    c.msg(turnComplete);
    tick(3);
    c.msg(said('Is it sorted?'));
    expect(lines().slice(1)).toEqual([
      ['C', 'Is it sorted?'],
      ['I', 'That is a long answer.'],
    ]);
    tick(4); // past the playback end plus the grace period
    c.msg(said('Yes.'));
    expect(lines().slice(1)).toEqual([
      ['C', 'Is it sorted?'],
      ['I', 'That is a long answer.'],
      ['C', 'Yes.'],
    ]);
  });

  it('starts a new candidate turn once the grace period after turnComplete is over', async () => {
    const { c, lines, opening, tick, states } = await started();
    opening();
    c.msg(said('First.'));
    c.msg(audio(2400));
    c.msg(says('Okay.'));
    c.msg(turnComplete);
    tick(1.5);
    c.msg(said('Second.'));
    expect(states().at(-1)).toBe('thinking');
    expect(lines().slice(1)).toEqual([
      ['C', 'First.'],
      ['I', 'Okay.'],
      ['C', 'Second.'],
    ]);
  });

  it('sends the ordered transcript, without partial marks, to the report', async () => {
    const { live, c, reports, events, opening, tick } = await started();
    opening();
    c.msg(audio(4800));
    c.msg(says('Tell me '));
    c.msg(said('My plan is'));
    c.msg(says(' more.'));
    c.msg(generationComplete);
    c.msg(said(' a heap.'));
    c.msg(turnComplete);
    tick(2);
    // The live view marks the line still taking text.
    c.msg(said('It is O(n log n).'));
    const view = events.filter(([e]) => e === 'transcript').at(-1)![1].turns;
    expect(view.at(-1)).toMatchObject({ text: 'It is O(n log n).', partial: true });

    live.emit('end_interview', {});
    c.msg(audio(480));
    c.msg(says('Good. That is all.'));
    c.msg(turnComplete);
    await vi.waitFor(() => expect(reports).toHaveLength(1));
    expect(reports[0].transcript.map((t) => [t.role, t.text])).toEqual([
      ['interviewer', 'Hi, I am your interviewer.'],
      ['candidate', 'My plan is a heap.'],
      ['interviewer', 'Tell me more.'],
      ['candidate', 'It is O(n log n).'],
      ['interviewer', 'Good. That is all.'],
    ]);
    for (const turn of reports[0].transcript) {
      expect(Object.keys(turn).sort()).toEqual(['role', 't', 'text']);
    }
    // The UI ends with the same final transcript.
    const last = events.filter(([e]) => e === 'transcript').at(-1)![1].turns;
    expect(last).toEqual(reports[0].transcript);
  });
});

describe('time notes', () => {
  it('formats whole minutes, rounding the elapsed time', () => {
    expect(timeNote(17 * 60, 45 * 60)).toBe('[Time: 17 of 45 min elapsed, 28 left]');
    expect(timeNote(0, 45 * 60)).toBe('[Time: 0 of 45 min elapsed, 45 left]');
    expect(timeNote(35 * 60 - 0.1, 45 * 60)).toBe('[Time: 35 of 45 min elapsed, 10 left]');
    expect(timeNote(17 * 60 + 29, 45 * 60)).toBe('[Time: 17 of 45 min elapsed, 28 left]');
    expect(timeNote(17 * 60 + 31, 45 * 60)).toBe('[Time: 18 of 45 min elapsed, 27 left]');
    expect(timeNote(50 * 60, 45 * 60)).toBe('[Time: 45 of 45 min elapsed, 0 left]');
  });

  it('schedules every 5 minutes and at 10, 5 and 2 minutes left, once each', () => {
    const min = (xs: number[]) => xs.map((x) => x / 60);
    expect(min(timeNoteSchedule(45 * 60))).toEqual([5, 10, 15, 20, 25, 30, 35, 40, 43]);
    expect(min(timeNoteSchedule(12 * 60))).toEqual([2, 5, 7, 10]);
    expect(min(timeNoteSchedule(10 * 60))).toEqual([5, 8]);
  });

  // Advance the injected clock and the fake timers together.
  async function timed() {
    vi.useFakeTimers();
    const ctx = setup();
    await ctx.live.start({ track: 'debug' });
    const c = ctx.conns[0];
    // In steps of 0.5 s, so a timer sees the clock at the time it fires.
    const wait = (s: number) => {
      for (let i = 0; i < s * 2; i++) {
        ctx.tick(0.5);
        vi.advanceTimersByTime(500);
      }
    };
    const notes = () => c.texts.filter((t) => t.text.includes('[Time: ')).map((t) => t.text);
    return { ...ctx, c, wait, notes };
  }

  it('sends each scheduled note once, as hidden context', async () => {
    const { c, wait, notes } = await timed();
    wait(9 * 60);
    expect(notes()).toEqual([
      '[Time: 5 of 10 min elapsed, 5 left]',
      '[Time: 8 of 10 min elapsed, 2 left]',
    ]);
    expect(c.texts.filter((t) => t.text.startsWith('[Time: ')).every((t) => !t.turnComplete)).toBe(
      true
    );
  });

  it('puts the time on the first line of each code snapshot and skips a note within 60 s', async () => {
    const { live, c, wait, notes } = await timed();
    wait(4 * 60 + 30);
    live.emit('code_update', { code: 'x = 1' });
    wait(1); // the snapshot debounce
    const snap = c.texts.at(-1)!.text.split('\n');
    expect(snap[0]).toBe('[Time: 5 of 10 min elapsed, 5 left]');
    expect(snap[1]).toMatch(/^\[Candidate's current python code/);
    wait(29); // the 5-minute note falls 29 s after the snapshot: skipped
    expect(notes()).toHaveLength(1);
    wait(3 * 60); // the 2-minutes-left note is sent
    expect(notes()).toEqual([snap.join('\n'), '[Time: 8 of 10 min elapsed, 2 left]']);
  });

  it('sends no notes after wrap-up has started', async () => {
    const { live, c, wait, notes } = await timed();
    live.emit('end_interview', {});
    live.emit('code_update', { code: 'x = 2' });
    wait(9 * 60);
    expect(notes()).toEqual([]);
    expect(c.texts.at(-1)!.text).toMatch(/^\[Candidate's current python code/);
  });

  it('keeps the notes out of the transcript and the latency', async () => {
    const { live, c, wait, reports, events } = await timed();
    c.msg(audio(480));
    c.msg({ serverContent: { outputTranscription: { text: 'Hi.' } } });
    c.msg({ serverContent: { turnComplete: true } });
    c.msg({ serverContent: { inputTranscription: { text: 'Hello.' } } });
    wait(0.5);
    c.msg(audio(480));
    c.msg({ serverContent: { outputTranscription: { text: 'Go ahead.' } } });
    c.msg({ serverContent: { turnComplete: true } });
    live.emit('code_update', { code: 'y = 3' });
    wait(5 * 60);
    expect(c.texts.filter((t) => t.text.includes('[Time: '))).toHaveLength(2); // the snapshot's and the 5-minute note;
    expect(live.metrics().response_latency_ms_p50).toBe(500);
    live.emit('end_interview', {});
    c.msg({ serverContent: { turnComplete: true } });
    await vi.waitFor(() => expect(reports).toHaveLength(1));
    const all = JSON.stringify([reports[0].transcript, events.filter(([e]) => e === 'transcript')]);
    expect(all).not.toContain('[Time:');
    expect(reports[0].transcript.map((t) => t.text)).toEqual(['Hi.', 'Hello.', 'Go ahead.']);
  });
});
