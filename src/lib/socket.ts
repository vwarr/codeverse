import { io } from 'socket.io-client';

export const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:5100';

// One shared connection for the whole app. Pages subscribe/unsubscribe to events;
// they never create their own socket.
export const socket = io(BACKEND_URL, { autoConnect: true });
