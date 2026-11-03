// The browser's connection to the Gemini Live API, behind a small interface so LiveInterview can be
// tested with a fake. The real one uses @google/genai with the one-use ephemeral token from
// /api/session. The token locks the model, system instruction, tools and voice on Google's side;
// the browser only adds its session-resumption handle when it reconnects.

export interface LiveFunctionCall {
  id?: string;
  name?: string;
  args?: Record<string, unknown>;
}

/** The fields of LiveServerMessage that LiveInterview reads. */
export interface LiveMessage {
  toolCall?: { functionCalls?: LiveFunctionCall[] };
  serverContent?: {
    modelTurn?: { parts?: { inlineData?: { data?: string } }[] };
    // Sent independently of the other server messages, with no guaranteed ordering.
    inputTranscription?: { text?: string; finished?: boolean };
    outputTranscription?: { text?: string };
    interrupted?: boolean;
    generationComplete?: boolean;
    turnComplete?: boolean;
  };
  sessionResumptionUpdate?: { newHandle?: string; resumable?: boolean };
  goAway?: { timeLeft?: string };
}

export interface LiveConnectOptions {
  token: string;
  apiVersion: string;
  model: string;
  handle: string | null; // session-resumption handle; null for a new session
}

export interface LiveCallbacks {
  onMessage: (msg: LiveMessage) => void;
  onClose: (reason: string) => void;
}

export interface ToolResponse {
  id: string;
  name: string;
  response: Record<string, unknown>;
}

export interface LiveConnection {
  sendAudio: (base64Pcm16: string, mimeType: string) => void;
  sendText: (text: string, turnComplete: boolean) => void;
  sendToolResponse: (responses: ToolResponse[]) => void;
  close: () => void;
}

export type LiveConnector = (
  opts: LiveConnectOptions,
  callbacks: LiveCallbacks
) => Promise<LiveConnection>;

export const geminiConnector: LiveConnector = async (opts, callbacks) => {
  // Loaded on first use, so the SDK is not in the initial bundle.
  const { GoogleGenAI, Modality } = await import('@google/genai');
  const ai = new GoogleGenAI({ apiKey: opts.token, httpOptions: { apiVersion: opts.apiVersion } });
  const session = await ai.live.connect({
    model: opts.model,
    config: {
      responseModalities: [Modality.AUDIO],
      sessionResumption: opts.handle ? { handle: opts.handle } : {},
    },
    callbacks: {
      onmessage: (msg) => callbacks.onMessage(msg as LiveMessage),
      // eslint-disable-next-line no-console
      onerror: (e) => console.warn('Gemini Live error', e),
      onclose: (e) => callbacks.onClose(e.reason || `connection closed (${e.code})`),
    },
  });
  return {
    sendAudio: (data, mimeType) => session.sendRealtimeInput({ audio: { data, mimeType } }),
    sendText: (text, turnComplete) =>
      session.sendClientContent({ turns: [{ role: 'user', parts: [{ text }] }], turnComplete }),
    sendToolResponse: (functionResponses) => session.sendToolResponse({ functionResponses }),
    close: () => session.close(),
  };
};
