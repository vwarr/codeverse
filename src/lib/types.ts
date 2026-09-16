// Shapes shared with the backend (see backend/codeverse/sockets.py and problems/bank.py).

export type TrackId = 'swe' | 'ib' | 'quant';
export type Difficulty = 'easy' | 'medium' | 'hard';
export type Surface = 'editor' | 'conversation';

export interface Track {
  id: TrackId;
  name: string;
  description: string;
  surface: Surface;
  defaultDifficulty: Difficulty;
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
  problem: Problem;
  language: string;
  inputSampleRate: number;
  outputSampleRate: number;
  promptVersion: string;
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

export interface StartRequest {
  track: TrackId;
  problemId?: string;
  difficulty?: Difficulty;
  language?: string;
}

export type StartAck = { ok: true; session: SessionInfo } | { ok: false; error: string };
