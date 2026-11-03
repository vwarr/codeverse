// Demo mode (VITE_DEMO=1): a scripted in-browser stand-in replaces the API and Gemini, so the app
// can be hosted statically.
export const DEMO: boolean = !!import.meta.env.VITE_DEMO;

// Demo only: `?demoState=reconnecting|mic_denied|interviewer_wrap_up` shows that interview state,
// so each state can be seen (and screenshotted) without a live connection.
export type DemoState = 'reconnecting' | 'mic_denied' | 'interviewer_wrap_up';
export const DEMO_STATE: DemoState | null =
  DEMO && typeof window !== 'undefined'
    ? (new URLSearchParams(window.location.search).get('demoState') as DemoState | null)
    : null;
