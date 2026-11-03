// Shapes shared with the API functions (see backend/codeverse/web/service.py and problems/bank.py).

export type TrackId = 'swe' | 'debug';
export type Difficulty = 'easy' | 'medium' | 'hard';
export type Surface = 'editor';

export interface Track {
  id: TrackId;
  name: string;
  description: string;
  surface: Surface;
  defaultDifficulty: Difficulty;
  languages: string[]; // ['python'] on both tracks
  canRun: boolean;
}

export interface Example {
  input: string;
  output: string;
  explanation?: string | null;
}

export interface Problem {
  id: string;
  track: TrackId;
  title: string;
  difficulty: Difficulty;
  tags: string[];
  statement: string; // markdown
  examples: Example[];
  constraints: string[];
  starter_code: Record<string, string>;
  function_name?: string | null;
  module_name?: string | null; // debug track: the file name the tests import
  has_tests?: boolean; // the Run button has a hidden suite to run
}

export type SessionStatus =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'wrapping_up'
  | 'ended'
  | 'error';

export interface SessionInfo {
  sessionId: string;
  state: SessionStatus;
  track: TrackId;
  surface: Surface;
  languages: string[];
  canRun: boolean;
  problem: Problem;
  language: string;
  inputSampleRate: number;
  outputSampleRate: number;
  promptVersion: string;
  maxSeconds?: number; // the interviewer starts the wrap-up at this time
}

export interface TranscriptTurn {
  role: 'candidate' | 'interviewer';
  text: string;
  t: number;
}

export interface Dimension {
  name: string;
  score: number;
  justification: string;
}

export interface FeedbackReport {
  overall_score: number;
  summary: string;
  dimensions: Dimension[];
  strengths: string[];
  improvements: string[];
  model_answer_sketch: string;
  notable_moments: { quote: string; comment: string }[];
}

export interface SessionMetrics {
  model_turns: number;
  audio_in_seconds: number;
  audio_out_seconds: number;
  tool_calls: number;
  response_latency_ms_p50: number | null;
  response_latency_ms_max: number | null;
}

export interface TestOutcome {
  name: string;
  status: 'passed' | 'failed' | 'error' | 'skipped';
  message: string;
}

export interface RunResult {
  ok: boolean;
  passed: number;
  total: number;
  outcomes: TestOutcome[];
  stdout: string;
  stderr: string;
  load_error: string | null;
  timed_out: boolean;
  duration_ms: number;
}

export interface TestRun extends RunResult {
  run: number;
}

export type RunAck = { ok: true; result: TestRun } | { ok: false; error: string };

export interface StartRequest {
  track: TrackId;
  problemId?: string;
  difficulty?: Difficulty;
  language?: string;
}

export type StartAck = { ok: true; session: SessionInfo } | { ok: false; error: string };

/** POST /api/session: a one-use Gemini Live token plus the session the browser runs. */
export interface SessionGrant {
  ok: true;
  token: string;
  apiVersion: string;
  model: string;
  maxSeconds: number;
  expiresAt: string;
  codeDebounceSeconds: number;
  openingInstruction: string;
  wrapUpInstruction: string;
  session: SessionInfo;
}

export type RunResponse =
  | { ok: true; result: TestRun; summary: string }
  | { ok: false; error: string };

export interface ReportRequest {
  sessionId: string;
  transcript: TranscriptTurn[];
  code: string;
  metrics: SessionMetrics;
  /** Set when the Live connection dropped (rate limit/quota, or lost) and the interview ended early. */
  endReason?: 'quota' | 'connection_lost';
}

export type ReportResponse =
  | { ok: true; report: FeedbackReport; finalRun: RunResult | null }
  | { ok: false; error: string };

/** GET /api/report?sessionId=: the saved record. */
export interface ReportRecord {
  sessionId: string;
  track: TrackId;
  problemId: string;
  promptVersion?: string;
  createdAt: string;
  transcript: TranscriptTurn[];
  code: string;
  metrics: SessionMetrics | null;
  finalRun: RunResult | null;
  report: FeedbackReport | null; // null while the report is still being written
  status?: 'pending' | 'complete' | 'failed';
}

/** GET /api/report (no sessionId): saved reports for this address, newest first. */
export interface HistoryItem {
  sessionId: string;
  track: TrackId;
  problemId: string;
  problemTitle: string;
  difficulty: Difficulty | null;
  createdAt: string;
  overallScore: number | null;
}
