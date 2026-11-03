// Demo mode: an in-browser stand-in for the Socket.IO backend, used when the app is built with
// VITE_DEMO=1 (e.g. for a static host with no backend). It plays a scripted interview, voices the
// interviewer with the browser's speechSynthesis, returns precomputed test runs for the debugging
// track and a canned feedback report. It implements only the socket surface the app uses.

import { DEMO_STATE } from '../env';
import type {
  FeedbackReport,
  Problem,
  RunResult,
  SessionInfo,
  SessionMetrics,
  SessionStatus,
  StartRequest,
  TestRun,
  Track,
  TrackId,
  TranscriptTurn,
} from '../types';
import debugRuns from './debugRuns.json';
import { saveDemoReport } from './history';
import problemsData from './problems.json';
import sweRuns from './sweRuns.json';
import tracksData from './tracks.json';

export const DEMO_TRACKS = tracksData as Track[];
export const DEMO_PROBLEMS = problemsData as Problem[];

type Handler = (...args: any[]) => void;
type Ack = (res: unknown) => void;
type Line = { role: TranscriptTurn['role']; text: string };

const RUNS = debugRuns as Record<
  string,
  { buggy: RunResult; fixed: RunResult; fixed_code: string }
>;

// SWE track: real results of the hidden tests on each problem's starter code (see README).
const SWE_RUNS = sweRuns as Record<string, RunResult>;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function script(track: TrackId, p: Problem): Line[] {
  const I = (text: string): Line => ({ role: 'interviewer', text });
  const C = (text: string): Line => ({ role: 'candidate', text });
  switch (track) {
    case 'debug':
      return [
        I(
          `Hi, thanks for joining. Today we have a bug report: "${p.title}". The module is in the editor and you can press Run tests whenever you like. Talk me through how you'd start.`
        ),
        C(
          "Sure. Before touching anything I'd like to reproduce it, so I'll run the existing test suite and see what fails."
        ),
        I('Good instinct. Go ahead and press Run tests, then tell me what you see.'),
        C(
          'A few tests fail. The failures share some state between calls, which lines up with the report that it only shows up after the server has been running a while.'
        ),
        I('What is your hypothesis, and how would you confirm it before changing code?'),
        C(
          "My hypothesis is a value that should be per-call is being created once and reused. I'd write a tiny case that creates two objects and checks whether they share it."
        ),
        I(
          'Nice, that is exactly the kind of focused check I like. Make the fix, rerun the tests, and when you are happy press Finish.'
        ),
      ];
    default:
      return [
        I(
          `Hi, thanks for joining. Today's problem is ${p.title}. Take a moment to read it, and ask me anything that's unclear.`
        ),
        C(
          'Thanks. Can I assume the input fits in memory, and what should I return for an empty input?'
        ),
        I('Yes, it fits in memory. For an empty input, return the natural empty result.'),
        C(
          "OK. I'll start with the simplest correct approach and say what it costs, then look for a better one."
        ),
        I('What is the time and space complexity of the approach you settle on?'),
        C(
          "I'll state it once I've walked through the first example, so the numbers match the code. Let me write it up."
        ),
        I(
          'Sounds good. Go ahead in the editor, and press Finish when you are happy with your solution.'
        ),
      ];
  }
}

const RUBRIC: Record<TrackId, string[]> = {
  swe: [
    'Communication',
    'Problem decomposition',
    'Correctness',
    'Complexity analysis',
    'Code quality',
  ],
  debug: [
    'Communication',
    'Reproduction and evidence',
    'Hypothesis-driven process',
    'Root cause and fix quality',
    'Verification and prevention',
  ],
};

function report(track: TrackId, p: Problem, transcript: TranscriptTurn[]): FeedbackReport {
  const scores = [4, 4, 3, 4, 3];
  const quote = transcript.find((t) => t.role === 'candidate')?.text ?? '';
  return {
    overall_score: 4,
    summary: `A clear, well-structured attempt at ${p.title}. You explained your reasoning before acting; the next step is tighter verification at the end. (This is a sample report: the hosted demo uses a scripted interviewer, not a live model.)`,
    dimensions: RUBRIC[track].map((name, i) => ({
      name,
      score: scores[i % scores.length],
      justification:
        scores[i % scores.length] >= 4
          ? 'Consistently strong; reasoning was stated before each step.'
          : 'Solid, with room to be more explicit about edge cases and checks.',
    })),
    strengths: [
      'Stated assumptions up front',
      'Chose an approach and explained why before committing',
      'Responded well to follow-up questions',
    ],
    improvements: [
      'Walk through one concrete example end to end before finishing',
      'Name the edge cases you are deliberately not handling',
    ],
    model_answer_sketch:
      track === 'debug'
        ? '1. Reproduce with the test suite.\n2. Isolate the shared state with a minimal case.\n3. Fix the root cause, not the symptom.\n4. Rerun the suite and add a regression test.'
        : '1. Clarify inputs and edge cases.\n2. State the brute force and its cost.\n3. Improve with the right structure and justify it.\n4. Verify on an example and state complexity.',
    notable_moments: quote
      ? [{ quote, comment: 'A good opening: it set up the rest of the conversation.' }]
      : [],
  };
}

export class DemoSocket {
  connected = true;
  private handlers = new Map<string, Set<Handler>>();
  private session: SessionInfo | null = null;
  private transcript: TranscriptTurn[] = [];
  private t0 = 0;
  private gen = 0; // bumps on every new interview / end, cancelling the running script
  private runs = 0;
  private code = '';
  private spokenSeconds = { in: 0, out: 0 };

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

  timeout(_ms: number) {
    return {
      emit: (event: string, data: unknown, cb: (err: Error | null, res: unknown) => void) =>
        this.handle(event, data, (res) => cb(null, res)),
    };
  }

  emit(event: string, data?: unknown, cb?: Ack) {
    this.handle(event, data, cb);
    return this;
  }

  private fire(event: string, data?: unknown) {
    this.handlers.get(event)?.forEach((h) => h(data));
  }

  private handle(event: string, data: unknown, ack?: Ack) {
    switch (event) {
      case 'start_interview':
        ack?.(this.start(data as StartRequest));
        return;
      case 'code_update':
        this.code = String((data as { code?: string })?.code ?? '');
        return;
      case 'run_tests':
        void this.runTests(String((data as { code?: string })?.code ?? this.code), ack);
        return;
      case 'end_interview':
        ack?.({ ok: true, sessionId: this.session?.sessionId });
        void this.finish();
    }
  }

  private start(req: StartRequest) {
    const track = DEMO_TRACKS.find((t) => t.id === req.track) ?? DEMO_TRACKS[0];
    const pool = DEMO_PROBLEMS.filter(
      (p) => p.track === track.id && (!req.difficulty || p.difficulty === req.difficulty)
    );
    const problem =
      DEMO_PROBLEMS.find((p) => p.id === req.problemId) ??
      pool[Math.floor(Math.random() * pool.length)] ??
      DEMO_PROBLEMS.find((p) => p.track === track.id)!;
    const language = 'python';
    this.session = {
      sessionId: `demo-${Date.now().toString(36)}`,
      state: 'connecting',
      track: track.id,
      surface: track.surface,
      languages: track.languages,
      canRun: track.canRun && problem.has_tests !== false,
      problem,
      language,
      inputSampleRate: 16000,
      outputSampleRate: 24000,
      promptVersion: 'demo',
      maxSeconds: 45 * 60,
    };
    this.transcript = [];
    this.runs = 0;
    this.code = problem.starter_code[language] ?? '';
    this.spokenSeconds = { in: 0, out: 0 };
    this.t0 = performance.now();
    const gen = ++this.gen;
    this.fire('interview_started', { session: this.session });
    void this.play(gen, script(track.id, problem)).then(() => this.afterScript(gen));
    return { ok: true, session: this.session };
  }

  /** `?demoState=…`: show one interview state after the scripted opening. */
  private async afterScript(gen: number) {
    if (gen !== this.gen) {
      return;
    }
    if (DEMO_STATE === 'reconnecting') {
      this.fire('connection', { reconnecting: true });
    } else if (DEMO_STATE === 'interviewer_wrap_up') {
      this.setState('wrapping_up', 'interviewer');
      await this.say(gen, {
        role: 'interviewer',
        text: 'We have covered everything I wanted to. Thanks for your time; here is a short summary before your written report.',
      });
      // As in the live flow, the end of the closing turn ends the interview.
      if (gen === this.gen && this.session) {
        await this.end(this.session);
      }
    }
  }

  private setState(state: SessionStatus, reason?: string) {
    this.fire('session_state', { state, reason });
  }

  private async say(gen: number, line: Line) {
    const words = line.text.split(' ');
    const speaking = line.role === 'interviewer';
    const msPerWord = speaking ? 260 : 200;
    let spoken: Promise<void> = Promise.resolve();
    if (speaking && typeof window.speechSynthesis?.speak === 'function') {
      spoken = new Promise((resolve) => {
        const u = new SpeechSynthesisUtterance(line.text);
        u.rate = 1.05;
        u.onend = () => resolve();
        u.onerror = () => resolve();
        window.speechSynthesis.speak(u);
        // Some browsers never fire onend; don't hang the demo on it.
        setTimeout(resolve, words.length * 600 + 2000);
      });
    }
    for (const w of words) {
      if (gen !== this.gen) {
        return;
      }
      this.fire('transcript_delta', { role: line.role, text: `${w} ` });
      await sleep(msPerWord);
    }
    await spoken;
    if (gen !== this.gen) {
      return;
    }
    const turn: TranscriptTurn = {
      role: line.role,
      text: line.text,
      t: Math.round((performance.now() - this.t0) / 100) / 10,
    };
    this.transcript.push(turn);
    this.fire('transcript_turn', turn);
    const secs = (words.length * msPerWord) / 1000;
    if (speaking) {
      this.spokenSeconds.out += secs;
    } else {
      this.spokenSeconds.in += secs;
    }
  }

  private async play(gen: number, lines: Line[]) {
    await sleep(900);
    for (const line of lines) {
      if (gen !== this.gen) {
        return;
      }
      if (line.role === 'interviewer') {
        this.setState('thinking');
        await sleep(500);
        this.setState('speaking');
      } else {
        this.setState('listening');
        await sleep(1200);
      }
      await this.say(gen, line);
    }
    if (gen === this.gen) {
      this.setState('listening');
    }
  }

  /** The demo has no runner: it plays back real results recorded from the hidden suites. */
  private demoRun(code: string): RunResult | string {
    const problem = this.session?.problem;
    if (!problem) {
      return 'The interview is not in progress.';
    }
    const norm = (s: string) => s.replace(/\s+/g, '');
    const debug = RUNS[problem.id];
    if (debug) {
      return norm(code) === norm(debug.fixed_code) ? debug.fixed : debug.buggy;
    }
    const swe = SWE_RUNS[problem.id];
    if (!swe) {
      return 'Tests are not available for this problem in the demo.';
    }
    if (norm(code) !== norm(problem.starter_code.python ?? '')) {
      return 'The demo can only run the starter code. Run the app with the API to test your own code.';
    }
    return swe;
  }

  private async runTests(code: string, ack?: Ack) {
    await sleep(700);
    const base = this.demoRun(code);
    if (typeof base === 'string') {
      ack?.({ ok: false, error: base });
      return;
    }
    const run: TestRun = { ...base, run: ++this.runs };
    this.fire('run_result', run);
    ack?.({ ok: true, result: run });
  }

  private async finish() {
    const session = this.session;
    if (!session) {
      return;
    }
    const gen = ++this.gen;
    if (typeof window.speechSynthesis?.speak === 'function') {
      window.speechSynthesis.cancel();
    }
    this.fire('connection', { reconnecting: false });
    this.setState('wrapping_up', 'candidate');
    await this.say(gen, {
      role: 'interviewer',
      text: 'Thanks, that was great. I will put together your feedback now.',
    });
    await this.end(session);
  }

  /** Metrics, the final test run (debugging track), the saved report. */
  private async end(session: SessionInfo) {
    this.gen++;
    const metrics: SessionMetrics = {
      model_turns: this.transcript.filter((t) => t.role === 'interviewer').length,
      audio_in_seconds: Math.round(this.spokenSeconds.in),
      audio_out_seconds: Math.round(this.spokenSeconds.out),
      tool_calls: 0,
      response_latency_ms_p50: 640,
      response_latency_ms_max: 910,
    };
    this.fire('interview_ended', { sessionId: session.sessionId, metrics });
    // Only the Debugging track grades the final code (as the API does).
    let finalRun: RunResult | null = null;
    if (session.track === 'debug') {
      await sleep(800);
      const run = this.demoRun(this.code);
      if (typeof run !== 'string') {
        finalRun = run;
        this.fire('final_tests', run);
      }
    }
    await sleep(1500);
    const feedback = report(session.track, session.problem, this.transcript);
    saveDemoReport({
      sessionId: session.sessionId,
      track: session.track,
      problemId: session.problem.id,
      promptVersion: 'demo',
      createdAt: new Date().toISOString(),
      transcript: [...this.transcript],
      code: this.code,
      metrics,
      finalRun,
      report: feedback,
    });
    this.fire('feedback', { sessionId: session.sessionId, report: feedback });
  }
}
