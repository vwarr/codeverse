import { AudioEngine } from './engine';

// The real MicCapture needs getUserMedia and an AudioWorklet. This fake keeps the frame callback
// and the muted flag, so the test can push frames as the worklet would.
const fake = vi.hoisted(() => ({
  onFrame: null as ((f: ArrayBuffer) => void) | null,
  muted: false,
}));

vi.mock('./capture', () => ({
  MicCapture: class {
    requestPermission = async () => 'granted';
    start = async (_rate: number, onFrame: (f: ArrayBuffer) => void) => {
      fake.onFrame = onFrame;
    };
    setMuted = (m: boolean) => {
      fake.muted = m;
    };
    stop = () => undefined;
  },
}));

vi.mock('./player', () => ({
  PcmPlayer: class {
    resume = async () => undefined;
    enqueue = () => undefined;
    flush = () => undefined;
    close = () => undefined;
  },
}));

describe('AudioEngine mute', () => {
  it('stops sending microphone frames while muted', async () => {
    const sent: ArrayBuffer[] = [];
    const engine = new AudioEngine();
    await engine.start(16000, 24000, (f) => sent.push(f));
    fake.onFrame!(new ArrayBuffer(2));
    expect(sent).toHaveLength(1);

    engine.setMuted(true);
    expect(engine.isMuted).toBe(true);
    expect(fake.muted).toBe(true); // the track is disabled too
    fake.onFrame!(new ArrayBuffer(2));
    fake.onFrame!(new ArrayBuffer(2));
    expect(sent).toHaveLength(1);

    engine.setMuted(false);
    expect(fake.muted).toBe(false);
    fake.onFrame!(new ArrayBuffer(2));
    expect(sent).toHaveLength(2);
  });
});
