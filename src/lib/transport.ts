import { httpApi } from './api';
import { DemoSocket } from './demo/demoSocket';
import { DEMO } from './env';
import { geminiConnector } from './live/connector';
import { LiveInterview } from './live/LiveInterview';

export { DEMO };

type Handler = (...args: any[]) => void;

/** The event surface InterviewProvider uses. LiveInterview and DemoSocket both implement it. */
export interface InterviewTransport {
  readonly connected: boolean;
  on: (event: string, h: Handler) => unknown;
  off: (event: string, h: Handler) => unknown;
  emit: (event: string, data?: unknown, ack?: (res: any) => void) => unknown;
  timeout: (ms: number) => {
    emit: (event: string, data: unknown, cb: (err: Error | null, res: any) => void) => void;
  };
}

// One interview runner for the whole app. Pages subscribe and unsubscribe to its events.
export const transport: InterviewTransport = DEMO
  ? new DemoSocket()
  : new LiveInterview({ api: httpApi, connect: geminiConnector });
