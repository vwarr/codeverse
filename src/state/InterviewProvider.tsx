import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from 'react';
import { socket } from '../lib/socket';
import type {
  FeedbackReport,
  SessionInfo,
  SessionMetrics,
  SessionStatus,
  StartAck,
  StartRequest,
  TranscriptTurn,
} from '../lib/types';
import { initialInterviewState, interviewReducer, InterviewState } from './interview';

interface InterviewApi {
  state: InterviewState;
  start: (req: StartRequest) => Promise<StartAck>;
  finish: () => void;
  sendCode: (code: string, language: string) => void;
  reset: () => void;
}

const InterviewContext = createContext<InterviewApi | null>(null);

export function InterviewProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(interviewReducer, initialInterviewState);

  useEffect(() => {
    const onConnect = () => dispatch({ type: 'connected', connected: true });
    const onDisconnect = () => dispatch({ type: 'connected', connected: false });
    const onStarted = (data: { session: SessionInfo }) =>
      dispatch({ type: 'started', session: data.session });
    const onState = (data: { state: SessionStatus; reason?: string }) =>
      dispatch({ type: 'state', state: data.state, reason: data.reason });
    const onDelta = (data: { role: TranscriptTurn['role']; text: string }) =>
      dispatch({ type: 'transcript_delta', role: data.role, text: data.text });
    const onTurn = (turn: TranscriptTurn) => dispatch({ type: 'transcript_turn', turn });
    const onInterrupted = () => dispatch({ type: 'interrupted' });
    const onFeedback = (data: { report: FeedbackReport }) =>
      dispatch({ type: 'feedback', report: data.report });
    const onEnded = (data: { metrics: SessionMetrics }) =>
      dispatch({ type: 'ended', metrics: data.metrics });
    const onError = (data: { message?: string }) =>
      dispatch({ type: 'error', message: data?.message ?? 'Unknown error' });

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('interview_started', onStarted);
    socket.on('session_state', onState);
    socket.on('transcript_delta', onDelta);
    socket.on('transcript_turn', onTurn);
    socket.on('interrupted', onInterrupted);
    socket.on('feedback', onFeedback);
    socket.on('interview_ended', onEnded);
    socket.on('error', onError);
    if (socket.connected) {
      onConnect();
    }
    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('interview_started', onStarted);
      socket.off('session_state', onState);
      socket.off('transcript_delta', onDelta);
      socket.off('transcript_turn', onTurn);
      socket.off('interrupted', onInterrupted);
      socket.off('feedback', onFeedback);
      socket.off('interview_ended', onEnded);
      socket.off('error', onError);
    };
  }, []);

  const start = useCallback(async (req: StartRequest): Promise<StartAck> => {
    dispatch({ type: 'start_requested' });
    const ack = await new Promise<StartAck>((resolve) => {
      socket.timeout(15000).emit('start_interview', req, (err: Error | null, res: StartAck) => {
        if (err) {
          resolve({ ok: false, error: 'The backend did not answer. Is it running?' });
        } else {
          resolve(res);
        }
      });
    });
    if (!ack.ok) {
      dispatch({ type: 'start_failed', error: ack.error });
    }
    return ack;
  }, []);

  const finish = useCallback(() => {
    socket.emit('end_interview', {});
  }, []);

  const sendCode = useCallback((code: string, language: string) => {
    socket.emit('code_update', { code, language });
  }, []);

  const reset = useCallback(() => dispatch({ type: 'reset' }), []);

  const api = useMemo<InterviewApi>(
    () => ({ state, start, finish, sendCode, reset }),
    [state, start, finish, sendCode, reset]
  );

  return <InterviewContext.Provider value={api}>{children}</InterviewContext.Provider>;
}

export function useInterview(): InterviewApi {
  const ctx = useContext(InterviewContext);
  if (!ctx) {
    throw new Error('useInterview must be used inside InterviewProvider');
  }
  return ctx;
}
