// Pure reducer for the interview lifecycle. The socket wiring lives in InterviewProvider.

import type {
  FeedbackReport,
  SessionInfo,
  SessionMetrics,
  SessionStatus,
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
  connected: boolean;
}

export type InterviewAction =
  | { type: 'reset' }
  | { type: 'start_requested' }
  | { type: 'started'; session: SessionInfo }
  | { type: 'start_failed'; error: string }
  | { type: 'state'; state: SessionStatus; reason?: string }
  | { type: 'transcript_delta'; role: TranscriptTurn['role']; text: string }
  | { type: 'transcript_turn'; turn: TranscriptTurn }
  | { type: 'interrupted' }
  | { type: 'feedback'; report: FeedbackReport }
  | { type: 'ended'; metrics: SessionMetrics }
  | { type: 'error'; message: string }
  | { type: 'mic'; mic: MicState }
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
  connected: false,
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
      return { ...state, status: action.session.state, session: action.session, error: null };
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
        live: { candidate: '', interviewer: '' },
      };
    case 'error':
      return { ...state, status: 'error', error: action.message };
    case 'mic':
      return { ...state, mic: action.mic };
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
  listening: 'Your turn — speak',
  thinking: 'Interviewer is thinking',
  speaking: 'Interviewer is speaking',
  wrapping_up: 'Wrapping up',
  ended: 'Interview over',
  error: 'Something went wrong',
};

export function isLive(status: InterviewState['status']): boolean {
  return (
    status === 'listening' ||
    status === 'thinking' ||
    status === 'speaking' ||
    status === 'wrapping_up'
  );
}
