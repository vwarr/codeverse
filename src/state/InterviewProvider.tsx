import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react';
import { AudioEngine } from '../lib/audio/engine';
import { DEMO_STATE } from '../lib/env';
import { DEMO, transport } from '../lib/transport';
import type {
  FeedbackReport,
  RunAck,
  RunResult,
  SessionInfo,
  SessionMetrics,
  SessionStatus,
  StartAck,
  StartRequest,
  TestRun,
  TranscriptTurn,
} from '../lib/types';
import { initialInterviewState, interviewReducer, InterviewState } from './interview';

interface InterviewApi {
  state: InterviewState;
  start: (req: StartRequest) => Promise<StartAck>;
  finish: () => void;
  sendCode: (code: string, language: string) => void;
  runTests: (code: string) => Promise<RunAck>;
  setMuted: (muted: boolean) => void;
  reset: () => void;
}

const MIC_DENIED =
  'Microphone access is blocked. Allow the microphone for this site in the browser settings, then press Start interview again.';

const InterviewContext = createContext<InterviewApi | null>(null);

export function InterviewProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(interviewReducer, initialInterviewState);
  // One AudioEngine per interview; created inside the Start click so the browser lets us open
  // the mic and an AudioContext.
  const audio = useRef<AudioEngine | null>(null);

  const stopAudio = useCallback(() => {
    audio.current?.stop();
    audio.current = null;
    dispatch({ type: 'mic', mic: 'off' });
  }, []);

  useEffect(() => {
    const onConnect = () => dispatch({ type: 'connected', connected: true });
    const onDisconnect = () => {
      dispatch({ type: 'connected', connected: false });
      stopAudio();
    };
    const onStarted = async (data: { session: SessionInfo }) => {
      dispatch({ type: 'started', session: data.session, at: Date.now() });
      const engine = audio.current;
      if (!engine) {
        return;
      }
      try {
        await engine.start(data.session.inputSampleRate, data.session.outputSampleRate, (frame) =>
          transport.emit('audio_in', frame)
        );
        dispatch({ type: 'mic', mic: 'on' });
      } catch (e) {
        dispatch({ type: 'error', message: `Could not start audio: ${(e as Error).message}` });
      }
    };
    const onState = (data: { state: SessionStatus; reason?: string }) =>
      dispatch({ type: 'state', state: data.state, reason: data.reason });
    const onAudioOut = (chunk: ArrayBuffer) => audio.current?.play(chunk);
    const onDelta = (data: { role: TranscriptTurn['role']; text: string }) =>
      dispatch({ type: 'transcript_delta', role: data.role, text: data.text });
    const onTurn = (turn: TranscriptTurn) => dispatch({ type: 'transcript_turn', turn });
    const onInterrupted = () => {
      audio.current?.interrupt();
      dispatch({ type: 'interrupted' });
    };
    const onFeedback = (data: { report: FeedbackReport }) =>
      dispatch({ type: 'feedback', report: data.report });
    const onEnded = (data: { metrics: SessionMetrics }) => {
      dispatch({ type: 'ended', metrics: data.metrics });
      stopAudio();
    };
    const onConnection = (data: { reconnecting: boolean }) =>
      dispatch({ type: 'reconnecting', reconnecting: !!data?.reconnecting });
    const onRunResult = (run: TestRun) => dispatch({ type: 'run_result', run });
    const onFinalTests = (result: RunResult) => dispatch({ type: 'final_tests', result });
    const onError = (data: { message?: string }) => {
      dispatch({ type: 'error', message: data?.message ?? 'Unknown error' });
      stopAudio();
    };

    transport.on('connect', onConnect);
    transport.on('disconnect', onDisconnect);
    transport.on('interview_started', onStarted);
    transport.on('session_state', onState);
    transport.on('audio_out', onAudioOut);
    transport.on('transcript_delta', onDelta);
    transport.on('transcript_turn', onTurn);
    transport.on('interrupted', onInterrupted);
    transport.on('feedback', onFeedback);
    transport.on('interview_ended', onEnded);
    transport.on('connection', onConnection);
    transport.on('run_result', onRunResult);
    transport.on('final_tests', onFinalTests);
    transport.on('error', onError);
    if (transport.connected) {
      onConnect();
    }
    return () => {
      transport.off('connect', onConnect);
      transport.off('disconnect', onDisconnect);
      transport.off('interview_started', onStarted);
      transport.off('session_state', onState);
      transport.off('audio_out', onAudioOut);
      transport.off('transcript_delta', onDelta);
      transport.off('transcript_turn', onTurn);
      transport.off('interrupted', onInterrupted);
      transport.off('feedback', onFeedback);
      transport.off('interview_ended', onEnded);
      transport.off('connection', onConnection);
      transport.off('run_result', onRunResult);
      transport.off('final_tests', onFinalTests);
      transport.off('error', onError);
      stopAudio();
    };
  }, [stopAudio]);

  const start = useCallback(
    async (req: StartRequest): Promise<StartAck> => {
      dispatch({ type: 'start_requested' });

      if (DEMO && DEMO_STATE === 'mic_denied') {
        dispatch({ type: 'mic', mic: 'denied' });
        const error = MIC_DENIED;
        dispatch({ type: 'start_failed', error });
        return { ok: false, error };
      }
      if (DEMO) {
        // The demo interviewer is scripted: no microphone, no audio stream.
        return new Promise<StartAck>((resolve) => {
          transport.emit('start_interview', req, (ack: StartAck) => {
            if (!ack.ok) {
              dispatch({ type: 'start_failed', error: ack.error });
            }
            resolve(ack);
          });
        });
      }

      // Microphone first: no point starting an interview nobody can talk to.
      const engine = new AudioEngine();
      dispatch({ type: 'mic', mic: 'requesting' });
      const permission = await engine.requestMic();
      if (permission !== 'granted') {
        dispatch({ type: 'mic', mic: permission });
        const error =
          permission === 'denied'
            ? MIC_DENIED
            : 'This browser cannot capture audio (no AudioWorklet / getUserMedia).';
        dispatch({ type: 'start_failed', error });
        return { ok: false, error };
      }
      audio.current = engine;

      const ack = await new Promise<StartAck>((resolve) => {
        transport
          .timeout(30000)
          .emit('start_interview', req, (err: Error | null, res: StartAck) => {
            if (err) {
              resolve({ ok: false, error: 'The server did not answer. Try again.' });
            } else {
              resolve(res);
            }
          });
      });
      if (!ack.ok) {
        dispatch({ type: 'start_failed', error: ack.error });
        stopAudio();
      }
      return ack;
    },
    [stopAudio]
  );

  const finish = useCallback(() => {
    transport.emit('end_interview', {});
  }, []);

  const sendCode = useCallback((code: string, language: string) => {
    transport.emit('code_update', { code, language });
  }, []);

  const runTests = useCallback(async (code: string): Promise<RunAck> => {
    dispatch({ type: 'run_requested' });
    const ack = await new Promise<RunAck>((resolve) => {
      transport.timeout(30000).emit('run_tests', { code }, (err: Error | null, res: RunAck) => {
        resolve(err ? { ok: false, error: 'The test run did not finish in time.' } : res);
      });
    });
    // A successful result also arrives as a run_result event; the ack covers failures.
    if (ack.ok) {
      dispatch({ type: 'run_result', run: ack.result });
    } else {
      dispatch({ type: 'run_failed', error: ack.error });
    }
    return ack;
  }, []);

  const setMuted = useCallback((muted: boolean) => {
    audio.current?.setMuted(muted);
    dispatch({ type: 'muted', muted });
  }, []);

  const reset = useCallback(() => {
    stopAudio();
    dispatch({ type: 'reset' });
  }, [stopAudio]);

  const api = useMemo<InterviewApi>(
    () => ({ state, start, finish, sendCode, runTests, setMuted, reset }),
    [state, start, finish, sendCode, runTests, setMuted, reset]
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
