// Pure reducer for the interview lifecycle. The socket wiring lives in InterviewProvider.

import type {
  FeedbackReport,
  RunResult,
  SessionInfo,
  SessionMetrics,
  SessionStatus,
  TestRun,
  TranscriptTurn,
} from '../lib/types';

export type MicState = 'off' | 'requesting' | 'on' | 'denied' | 'unsupported';

export interface InterviewState {
  status: SessionStatus | 'starting';
  session: SessionInfo | null;
  transcript: TranscriptTurn[];
  live: { candidate: string; interviewer: string };
  report: FeedbackReport | null;
  metrics: SessionMetrics | null;
  error: string | null;
  wrapUpReason: string | null;
  mic: MicState;
  muted: boolean;
  // The voice connection dropped and the interview is resuming it (the Live API closes each
  // connection after about ten minutes).
  reconnecting: boolean;
  // Date.now() when the interview started, for the time-remaining clock.
  startedAt: number | null;
  connected: boolean;
  // Debug track: the candidate's most recent test run, whether one is in flight, and the
  // grader's run on the final code after the interview.
  lastRun: TestRun | null;
  running: boolean;
  runError: string | null;
  finalRun: RunResult | null;
}

export type InterviewAction =
  | { type: 'reset' }
  | { type: 'start_requested' }
  | { type: 'started'; session: SessionInfo; at?: number }
  | { type: 'start_failed'; error: string }
  | { type: 'state'; state: SessionStatus; reason?: string }
  | { type: 'transcript_delta'; role: TranscriptTurn['role']; text: string }
  | { type: 'transcript_turn'; turn: TranscriptTurn }
  | { type: 'interrupted' }
  | { type: 'feedback'; report: FeedbackReport }
  | { type: 'ended'; metrics: SessionMetrics }
  | { type: 'error'; message: string }
  | { type: 'run_requested' }
  | { type: 'run_result'; run: TestRun }
  | { type: 'run_failed'; error: string }
  | { type: 'final_tests'; result: RunResult }
  | { type: 'mic'; mic: MicState }
  | { type: 'muted'; muted: boolean }
  | { type: 'reconnecting'; reconnecting: boolean }
  | { type: 'connected'; connected: boolean };

export const initialInterviewState: InterviewState = {
  status: 'idle',
  session: null,
  transcript: [],
  live: { candidate: '', interviewer: '' },
  report: null,
  metrics: null,
  error: null,
  wrapUpReason: null,
  mic: 'off',
  muted: false,
  reconnecting: false,
  startedAt: null,
  connected: false,
  lastRun: null,
  running: false,
  runError: null,
  finalRun: null,
};

export function interviewReducer(state: InterviewState, action: InterviewAction): InterviewState {
  switch (action.type) {
    case 'reset':
      return { ...initialInterviewState, connected: state.connected, mic: state.mic };
    case 'start_requested':
      return {
        ...initialInterviewState,
        connected: state.connected,
        mic: state.mic,
        status: 'starting',
      };
    case 'started':
      return {
        ...state,
        status: action.session.state,
        session: action.session,
        error: null,
        startedAt: action.at ?? null,
      };
    case 'start_failed':
      return { ...state, status: 'idle', error: action.error };
    case 'state':
      return {
        ...state,
        status: action.state,
        wrapUpReason: action.reason ?? state.wrapUpReason,
        session: state.session ? { ...state.session, state: action.state } : state.session,
      };
    case 'transcript_delta':
      return {
        ...state,
        live: { ...state.live, [action.role]: state.live[action.role] + action.text },
      };
    case 'transcript_turn':
      return {
        ...state,
        transcript: [...state.transcript, action.turn],
        live: { ...state.live, [action.turn.role]: '' },
      };
    case 'interrupted':
      return { ...state, live: { ...state.live, interviewer: '' } };
    case 'feedback':
      return { ...state, report: action.report };
    case 'ended':
      return {
        ...state,
        status: 'ended',
        metrics: action.metrics,
        reconnecting: false,
        live: { candidate: '', interviewer: '' },
      };
    case 'error':
      return { ...state, status: 'error', error: action.message, reconnecting: false };
    case 'run_requested':
      return { ...state, running: true, runError: null };
    case 'run_result':
      // Ignore a stale result arriving after a newer one.
      if (state.lastRun && action.run.run < state.lastRun.run) {
        return { ...state, running: false };
      }
      return { ...state, running: false, runError: null, lastRun: action.run };
    case 'run_failed':
      return { ...state, running: false, runError: action.error };
    case 'final_tests':
      return { ...state, finalRun: action.result };
    case 'mic':
      return { ...state, mic: action.mic, muted: action.mic === 'on' ? state.muted : false };
    case 'muted':
      return { ...state, muted: action.muted };
    case 'reconnecting':
      return { ...state, reconnecting: action.reconnecting };
    case 'connected':
      return { ...state, connected: action.connected };
    default:
      return state;
  }
}

export const STATUS_LABEL: Record<InterviewState['status'], string> = {
  idle: 'Not started',
  starting: 'Starting…',
  connecting: 'Connecting to the interviewer…',
  listening: 'Your turn to speak',
  thinking: 'Interviewer is thinking',
  speaking: 'Interviewer is speaking',
  wrapping_up: 'Wrapping up',
  ended: 'Interview over',
  error: 'Something went wrong',
};

/** The line in the interview header: one plain status, most important first. */
export function statusLine(state: InterviewState): string {
  if (state.reconnecting) {
    return 'Reconnecting to the interviewer…';
  }
  if (state.status === 'wrapping_up') {
    return state.wrapUpReason === 'interviewer'
      ? 'The interviewer is wrapping up'
      : state.wrapUpReason === 'time_limit'
        ? 'Time is up: wrapping up'
        : 'Wrapping up';
  }
  if (state.status === 'listening' && state.muted) {
    return 'Your turn to speak (microphone muted)';
  }
  return STATUS_LABEL[state.status];
}

/** Seconds left before the automatic wrap-up, or null when there is no limit. */
export function secondsLeft(state: InterviewState, now: number): number | null {
  const max = state.session?.maxSeconds;
  if (!max || state.startedAt == null) {
    return null;
  }
  return Math.max(0, Math.round(max - (now - state.startedAt) / 1000));
}

export function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function isLive(status: InterviewState['status']): boolean {
  return (
    status === 'listening' ||
    status === 'thinking' ||
    status === 'speaking' ||
    status === 'wrapping_up'
  );
}
