// One interview, run in the browser: the TypeScript port of backend/codeverse/sessions.py.
//
// It talks straight to Gemini Live with a one-use token from /api/session, answers the
// interviewer's tool calls from browser state (editor code, last test run), measures the latency
// of every model turn, reconnects with the session-resumption handle when the Live API closes a
// connection, and asks /api/report for the written report at the end.
//
// It exposes the same small event surface the Socket.IO client had (on/off/emit/timeout), so
// InterviewProvider and DemoSocket stay interchangeable.
//
// State machine
//   idle -> connecting -> listening <-> thinking <-> speaking -> wrapping_up -> ended
//                                    \-> error

import { UNREACHABLE, type InterviewApi } from '../api';
import type {
  RunAck,
  RunResult,
  SessionGrant,
  SessionInfo,
  SessionMetrics,
  SessionStatus,
  StartAck,
  StartRequest,
  TestRun,
  TranscriptTurn,
} from '../types';
import type {
  LiveConnection,
  LiveConnector,
  LiveFunctionCall,
  LiveMessage,
  ToolResponse,
} from './connector';

type Handler = (...args: any[]) => void;
type Role = TranscriptTurn['role'];

const AUDIO_IN_MIME = 'audio/pcm;rate=16000';
const MAX_RECONNECTS = 20;
const FINISH_WAIT_MS = 30_000;
const LIVE_STATES: SessionStatus[] = ['listening', 'thinking', 'speaking'];
const REPORT_RETRY_MS = 3000;
const RATE_LIMITED_MESSAGE =
  'The interviewer is over its usage limit (rate limit or quota). Try again in a few minutes.';

/** Why an interview ended early: the Live API hit a rate limit or quota, or the connection was lost. */
export type EndReason = 'quota' | 'connection_lost';

/** A Gemini 429 / RESOURCE_EXHAUSTED / quota error, from a close reason or an error message. */
export function isRateLimited(text: string): boolean {
  return /\b429\b|RESOURCE_EXHAUSTED|quota|rate limit/i.test(text);
}

interface TurnMetrics {
  candidateDoneAt: number | null; // seconds, from the clock
  firstAudioAt: number;
  audioBytes: number;
}

export function latencyMs(turn: TurnMetrics): number | null {
  return turn.candidateDoneAt == null
    ? null
    : Math.round((turn.firstAudioAt - turn.candidateDoneAt) * 1000);
}

export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i);
  }
  return out.buffer;
}

export function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

export interface LiveInterviewOptions {
  api: InterviewApi;
  connect: LiveConnector;
  clock?: () => number; // seconds
}

export class LiveInterview {
  // There is no long-lived server connection: the app is always "connected".
  readonly connected = true;

  private readonly api: InterviewApi;
  private readonly connector: LiveConnector;
  private readonly clock: () => number;
  private handlers = new Map<string, Set<Handler>>();

  // Per-interview state, reset in start().
  private grant: SessionGrant | null = null;
  private session: SessionInfo | null = null;
  private state: SessionStatus = 'idle';
  private startedAt = 0;
  private code = '';
  private language = 'python';
  private transcript: TranscriptTurn[] = [];
  private pending: Record<Role, string> = { candidate: '', interviewer: '' };
  private turns: TurnMetrics[] = [];
  private currentTurn: TurnMetrics | null = null;
  private lastCandidateAt: number | null = null;
  private audioInBytes = 0;
  private audioOutBytes = 0;
  private toolCalls = 0;
  private wrapUpStarted = false;
  private runCount = 0;
  private running = false;
  private lastRun: TestRun | null = null;
  private lastRunSummary = '';
  private lastRunCode: string | null = null;
  private lastRunAt: number | null = null;

  // Live connection.
  private conn: LiveConnection | null = null;
  private handle: string | null = null;
  private reconnects = 0;
  private closing = false;
  private outbox: ((c: LiveConnection) => void)[] = [];
  private codeTimer: ReturnType<typeof setTimeout> | null = null;
  private limitTimer: ReturnType<typeof setTimeout> | null = null;
  private endedResolve: (() => void) | null = null;
  private ended: Promise<void> = Promise.resolve();

  constructor(opts: LiveInterviewOptions) {
    this.api = opts.api;
    this.connector = opts.connect;
    this.clock = opts.clock ?? (() => performance.now() / 1000);
  }

  // ------------------------------------------------------------------ socket-like surface
  on(event: string, h: Handler) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(h);
    return this;
  }

  off(event: string, h: Handler) {
    this.handlers.get(event)?.delete(h);
    return this;
  }

  timeout(ms: number) {
    return {
      emit: (event: string, data: unknown, cb: (err: Error | null, res: unknown) => void) => {
        let done = false;
        const timer = setTimeout(() => {
          if (!done) {
            done = true;
            cb(new Error('timeout'), undefined);
          }
        }, ms);
        this.emit(event, data, (res: unknown) => {
          if (!done) {
            done = true;
            clearTimeout(timer);
            cb(null, res);
          }
        });
      },
    };
  }

  emit(event: string, data?: unknown, ack?: (res: any) => void) {
    switch (event) {
      case 'start_interview':
        void this.start(data as StartRequest).then((res) => ack?.(res));
        break;
      case 'audio_in':
        this.onAudio(data as ArrayBuffer);
        break;
      case 'code_update': {
        const d = (data ?? {}) as { code?: string; language?: string };
        this.onCode(String(d.code ?? ''), d.language);
        break;
      }
      case 'run_tests':
        void this.runTests((data as { code?: string } | undefined)?.code).then((r) => ack?.(r));
        break;
      case 'end_interview':
        void this.finish().then(() => ack?.({ ok: true, sessionId: this.session?.sessionId }));
        break;
    }
    return this;
  }

  private fire(event: string, data?: unknown) {
    this.handlers.get(event)?.forEach((h) => h(data));
  }

  // ------------------------------------------------------------------ helpers
  private now(): number {
    return this.clock() - this.startedAt;
  }

  private setState(state: SessionStatus, extra: Record<string, unknown> = {}) {
    if (this.state === state && Object.keys(extra).length === 0) {
      return;
    }
    this.state = state;
    this.fire('session_state', { state, sessionId: this.session?.sessionId, ...extra });
  }

  private isLive(): boolean {
    return LIVE_STATES.includes(this.state);
  }

  /** Send now, or as soon as the connection is back (after a reconnect). */
  private send(fn: (c: LiveConnection) => void) {
    if (this.conn) {
      fn(this.conn);
    } else {
      this.outbox.push(fn);
    }
  }

  private sendText(text: string, turnComplete: boolean) {
    this.send((c) => c.sendText(text, turnComplete));
  }

  metrics(): SessionMetrics {
    const lat = this.turns
      .map(latencyMs)
      .filter((x): x is number => x != null)
      .sort((a, b) => a - b);
    return {
      model_turns: this.turns.length,
      audio_in_seconds: Math.round((this.audioInBytes / (2 * 16000)) * 10) / 10,
      audio_out_seconds: Math.round((this.audioOutBytes / (2 * 24000)) * 10) / 10,
      tool_calls: this.toolCalls,
      response_latency_ms_p50: lat.length ? lat[Math.floor(lat.length / 2)] : null,
      response_latency_ms_max: lat.length ? lat[lat.length - 1] : null,
    };
  }

  // ------------------------------------------------------------------ lifecycle
  async start(req: StartRequest): Promise<StartAck> {
    if (this.session && !['ended', 'error'].includes(this.state)) {
      return { ok: false, error: 'An interview is already in progress.' };
    }
    this.reset();
    const grant = await this.api.createSession(req);
    if (!grant.ok) {
      return grant;
    }
    this.grant = grant;
    // The UI shows the time remaining, so the session carries the limit.
    this.session = { ...grant.session, maxSeconds: grant.maxSeconds };
    this.language = grant.session.language;
    this.startedAt = this.clock();
    this.fire('interview_started', { session: this.session });
    this.setState('connecting');
    try {
      await this.connectOnce();
    } catch (e) {
      const message = (e as Error).message;
      this.fail(
        isRateLimited(message)
          ? RATE_LIMITED_MESSAGE
          : `Could not start the interviewer: ${message}`
      );
      return { ok: true, session: this.session };
    }
    this.limitTimer = setTimeout(() => this.beginWrapUp('time_limit'), grant.maxSeconds * 1000);
    this.setState('thinking');
    this.sendText(grant.openingInstruction, true);
    return { ok: true, session: this.session };
  }

  private reset() {
    this.closeConnection();
    this.closing = false;
    this.grant = null;
    this.session = null;
    this.state = 'idle';
    this.code = '';
    this.transcript = [];
    this.pending = { candidate: '', interviewer: '' };
    this.turns = [];
    this.currentTurn = null;
    this.lastCandidateAt = null;
    this.audioInBytes = 0;
    this.audioOutBytes = 0;
    this.toolCalls = 0;
    this.wrapUpStarted = false;
    this.runCount = 0;
    this.running = false;
    this.lastRun = null;
    this.lastRunSummary = '';
    this.lastRunCode = null;
    this.lastRunAt = null;
    this.handle = null;
    this.reconnects = 0;
    this.outbox = [];
    this.ended = new Promise((resolve) => {
      this.endedResolve = resolve;
    });
  }

  onAudio(frame: ArrayBuffer) {
    // Dropped while reconnecting, rather than buffered: stale speech is worse than none.
    if (!this.isLive() || !this.conn) {
      return;
    }
    this.audioInBytes += frame.byteLength;
    this.conn.sendAudio(arrayBufferToBase64(frame), AUDIO_IN_MIME);
  }

  onCode(code: string, language?: string) {
    this.code = code;
    if (language) {
      this.language = language;
    }
    if (['ended', 'error', 'idle'].includes(this.state) || !this.grant) {
      return;
    }
    if (this.codeTimer) {
      clearTimeout(this.codeTimer);
    }
    this.codeTimer = setTimeout(() => {
      this.codeTimer = null;
      if (['ended', 'error'].includes(this.state)) {
        return;
      }
      const snapshot = this.code.trim() || '(empty editor)';
      this.sendText(
        `[Candidate's current ${this.language} code — for your reference, do not respond to this]\n${snapshot}`,
        false
      );
    }, this.grant.codeDebounceSeconds * 1000);
  }

  async runTests(code?: string): Promise<RunAck> {
    if (!this.session?.canRun) {
      return { ok: false, error: 'Running code is not available for this interview.' };
    }
    if (!this.isLive()) {
      return { ok: false, error: 'The interview is not in progress.' };
    }
    if (this.running) {
      return { ok: false, error: 'A run is already in progress.' };
    }
    if (code !== undefined) {
      this.code = code;
    }
    const snapshot = this.code;
    this.running = true;
    try {
      const res = await this.api.runTests(this.session.sessionId, snapshot);
      if (!res.ok) {
        return res;
      }
      this.runCount = res.result.run;
      this.lastRun = res.result;
      this.lastRunSummary = res.summary;
      this.lastRunCode = snapshot;
      this.lastRunAt = this.clock();
      this.fire('run_result', res.result);
      if (this.isLive()) {
        this.sendText(
          `[The candidate ran the test suite (run ${res.result.run}) — for your reference; ` +
            `respond only if they ask or it fits the conversation]\n${res.summary}`,
          false
        );
      }
      return { ok: true, result: res.result };
    } finally {
      this.running = false;
    }
  }

  /** Finish button, time limit or the request_wrap_up tool. False if already wrapping up. */
  beginWrapUp(reason: string, viaTool = false): boolean {
    if (this.wrapUpStarted || ['ended', 'error', 'idle'].includes(this.state)) {
      return false;
    }
    this.wrapUpStarted = true;
    if (this.codeTimer) {
      clearTimeout(this.codeTimer);
    }
    this.setState('wrapping_up', { reason });
    // When the model asked (via the tool), the instruction goes back in the tool result and the
    // model continues its turn; another user turn would make it close twice.
    if (!viaTool && this.grant) {
      this.sendText(this.grant.wrapUpInstruction, true);
    }
    return true;
  }

  /** Candidate pressed Finish: wrap up, wait (bounded) for the closing turn, then end. */
  async finish(): Promise<void> {
    if (['ended', 'error', 'idle'].includes(this.state)) {
      return;
    }
    if (this.state === 'connecting') {
      await this.end();
      return;
    }
    this.beginWrapUp('candidate');
    let timer: ReturnType<typeof setTimeout> | undefined;
    await Promise.race([
      this.ended,
      new Promise<void>((r) => {
        timer = setTimeout(r, FINISH_WAIT_MS);
      }),
    ]);
    clearTimeout(timer);
    await this.end();
  }

  private fail(message: string) {
    if (['ended', 'error'].includes(this.state)) {
      return;
    }
    this.fire('error', { message });
    this.setState('error');
    this.flushTranscript();
    this.stopTimers();
    this.closeConnection();
    this.endedResolve?.();
  }

  /** End the interview and ask for the report. `reason` is set when the Live connection dropped. */
  private async end(reason?: EndReason) {
    if (['ended', 'error'].includes(this.state) || !this.session) {
      return;
    }
    const session = this.session;
    this.flushTranscript();
    this.stopTimers();
    this.closeConnection(); // stop paying for audio before the report call
    const metrics = this.metrics();
    this.setState('ended', reason ? { metrics, reason } : { metrics });
    this.endedResolve?.();
    const request = {
      sessionId: session.sessionId,
      transcript: this.transcript,
      code: session.surface === 'editor' ? this.code : '',
      metrics,
      endReason: reason,
    };
    let res = await this.api.createReport(request);
    if (!res.ok && res.error.startsWith(UNREACHABLE)) {
      // The request never reached the server, so the transcript is not saved yet: try once more.
      await new Promise((r) => setTimeout(r, REPORT_RETRY_MS));
      res = await this.api.createReport(request);
    }
    if (res.ok) {
      if (res.finalRun) {
        this.fire('final_tests', { sessionId: session.sessionId, ...res.finalRun });
      }
      this.fire('feedback', { sessionId: session.sessionId, report: res.report });
    } else {
      this.fire('error', { message: res.error });
    }
    this.fire('interview_ended', { sessionId: session.sessionId, metrics });
  }

  private stopTimers() {
    for (const t of [this.codeTimer, this.limitTimer]) {
      if (t) {
        clearTimeout(t);
      }
    }
    this.codeTimer = null;
    this.limitTimer = null;
  }

  // ------------------------------------------------------------------ Live connection
  private async connectOnce(): Promise<void> {
    const grant = this.grant!;
    const conn = await this.connector(
      { token: grant.token, apiVersion: grant.apiVersion, model: grant.model, handle: this.handle },
      {
        onMessage: (msg) => this.onMessage(msg),
        onClose: (reason) => {
          if (this.conn === conn) {
            this.conn = null;
            void this.onConnectionClosed(reason);
          }
        },
      }
    );
    if (this.closing) {
      conn.close();
      return;
    }
    this.conn = conn;
    const queued = this.outbox;
    this.outbox = [];
    queued.forEach((fn) => fn(conn));
  }

  private closeConnection() {
    this.closing = true;
    const conn = this.conn;
    this.conn = null;
    conn?.close();
  }

  private async onConnectionClosed(reason: string) {
    if (this.closing || ['ended', 'error', 'idle'].includes(this.state)) {
      return;
    }
    // The Live API ends each connection after about ten minutes (with a GoAway first). Resume the
    // same conversation with the latest handle; the one-use token stays valid for resumption.
    if (this.handle) {
      this.fire('connection', { reconnecting: true });
    }
    // A rate limit or quota error will not go away by reconnecting.
    const limited = isRateLimited(reason);
    while (!limited && this.handle && this.reconnects < MAX_RECONNECTS && !this.closing) {
      const delay = Math.min(500 * 2 ** this.reconnects, 5000);
      this.reconnects += 1;
      try {
        await this.connectOnce();
        this.fire('connection', { reconnecting: false });
        return;
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('Gemini Live reconnect failed', e);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
    this.fire('connection', { reconnecting: false });
    if (this.closing) {
      return;
    }
    if (this.state === 'wrapping_up') {
      await this.end();
    } else if (this.transcript.length || this.pending.candidate || this.pending.interviewer) {
      // The interview had started: end it cleanly, keep the transcript and still ask for a report.
      await this.end(limited ? 'quota' : 'connection_lost');
    } else {
      this.fail(
        limited ? RATE_LIMITED_MESSAGE : `The voice connection closed unexpectedly (${reason}).`
      );
    }
  }

  private onMessage(msg: LiveMessage) {
    const update = msg.sessionResumptionUpdate;
    if (update?.resumable && update.newHandle) {
      this.handle = update.newHandle;
    }
    for (const call of msg.toolCall?.functionCalls ?? []) {
      this.runTool(call);
    }
    const content = msg.serverContent;
    if (!content) {
      return;
    }
    for (const part of content.modelTurn?.parts ?? []) {
      if (part.inlineData?.data) {
        this.onModelAudio(base64ToArrayBuffer(part.inlineData.data));
      }
    }
    if (content.inputTranscription?.text) {
      this.lastCandidateAt = this.clock();
      this.append('candidate', content.inputTranscription.text);
      if (this.state === 'listening') {
        this.setState('thinking');
      }
    }
    if (content.outputTranscription?.text) {
      this.append('interviewer', content.outputTranscription.text);
    }
    if (content.interrupted) {
      this.commit('interviewer');
      this.currentTurn = null;
      this.fire('interrupted', {});
      if (this.state === 'speaking' || this.state === 'thinking') {
        this.setState('listening');
      }
    }
    if (content.turnComplete) {
      this.commit('candidate');
      this.commit('interviewer');
      this.currentTurn = null;
      if (this.state === 'wrapping_up') {
        void this.end();
      } else if (this.state === 'speaking' || this.state === 'thinking') {
        this.setState('listening');
      }
    }
  }

  private onModelAudio(chunk: ArrayBuffer) {
    if (!this.currentTurn) {
      // Response latency: the candidate's last transcribed words -> the first audio byte.
      this.currentTurn = {
        candidateDoneAt: this.lastCandidateAt,
        firstAudioAt: this.clock(),
        audioBytes: 0,
      };
      this.turns.push(this.currentTurn);
      if (this.state === 'listening' || this.state === 'thinking') {
        this.setState('speaking');
      } else if (this.state === 'wrapping_up') {
        this.fire('session_state', {
          state: 'wrapping_up',
          sessionId: this.session?.sessionId,
          speaking: true,
        });
      }
    }
    this.currentTurn.audioBytes += chunk.byteLength;
    this.audioOutBytes += chunk.byteLength;
    this.fire('audio_out', chunk);
  }

  // ------------------------------------------------------------------ tools
  private runTool(call: LiveFunctionCall) {
    this.toolCalls += 1;
    const name = call.name ?? '';
    let result: Record<string, unknown>;
    switch (name) {
      case 'get_current_code': {
        const code = this.code.trim();
        result = {
          language: this.language,
          code: code || '(the candidate has not written any code yet)',
          line_count: code ? code.split('\n').length : 0,
        };
        break;
      }
      case 'get_last_test_run':
        result = this.lastRun
          ? {
              ran: true,
              runs_so_far: this.runCount,
              seconds_ago: Math.round(this.clock() - (this.lastRunAt ?? this.clock())),
              code_changed_since: this.code !== this.lastRunCode,
              summary: this.lastRunSummary,
            }
          : { ran: false, note: 'The candidate has not run the tests yet.' };
        break;
      case 'request_wrap_up':
        result = this.beginWrapUp('interviewer', true)
          ? { ok: true, instruction: this.grant?.wrapUpInstruction ?? '' }
          : {
              ok: false,
              note: 'The interview is already wrapping up; finish your closing remarks.',
            };
        break;
      default:
        result = { error: `unknown tool '${name}'` };
    }
    this.fire('tool_call', { name, args: call.args ?? {}, result });
    const response: ToolResponse = { id: call.id ?? '', name, response: result };
    this.send((c) => c.sendToolResponse([response]));
  }

  // ------------------------------------------------------------------ transcript
  private append(role: Role, fragment: string) {
    this.pending[role] += fragment;
    this.fire('transcript_delta', { role, text: fragment });
  }

  private flushRole(role: Role): TranscriptTurn | null {
    const text = this.pending[role].trim();
    this.pending[role] = '';
    if (!text) {
      return null;
    }
    const turn = { role, text, t: Math.round(this.now() * 100) / 100 };
    this.transcript.push(turn);
    return turn;
  }

  private commit(role: Role) {
    const turn = this.flushRole(role);
    if (turn) {
      this.fire('transcript_turn', turn);
    }
  }

  private flushTranscript() {
    this.flushRole('candidate');
    this.flushRole('interviewer');
  }

  /** For tests and debugging. */
  snapshot() {
    return {
      state: this.state,
      transcript: [...this.transcript],
      handle: this.handle,
      lastRun: this.lastRun as RunResult | null,
    };
  }
}
