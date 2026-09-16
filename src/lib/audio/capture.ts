// Microphone capture: getUserMedia -> AudioWorklet -> mono PCM16 frames at the backend's sample rate.
//
// The worklet source is inlined and loaded through a Blob URL so no extra file has to be served.
// It resamples from the AudioContext rate (usually 48 kHz) to `targetRate` with linear
// interpolation and posts Int16 frames of ~100 ms.

const WORKLET_SOURCE = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { targetRate, frameMs } = options.processorOptions;
    this.ratio = sampleRate / targetRate; // input samples per output sample
    this.frameSamples = Math.round((targetRate * frameMs) / 1000);
    this.frame = new Int16Array(this.frameSamples);
    this.filled = 0;
    this.pending = new Float32Array(0); // unconsumed input samples
    this.pos = 0; // fractional read position into pending
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    const merged = new Float32Array(this.pending.length + ch.length);
    merged.set(this.pending);
    merged.set(ch, this.pending.length);
    let pos = this.pos;
    while (pos + 1 < merged.length) {
      const i = Math.floor(pos);
      const frac = pos - i;
      const s = merged[i] + (merged[i + 1] - merged[i]) * frac;
      const v = Math.max(-1, Math.min(1, s));
      this.frame[this.filled++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.filled === this.frameSamples) {
        this.port.postMessage(this.frame.buffer.slice(0));
        this.filled = 0;
      }
      pos += this.ratio;
    }
    const keep = Math.floor(pos);
    this.pending = merged.slice(keep);
    this.pos = pos - keep;
    return true;
  }
}
registerProcessor('pcm-capture', PcmCaptureProcessor);
`;

export type MicPermission = 'granted' | 'denied' | 'unsupported';

export class MicCapture {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  static supported(): boolean {
    return (
      typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof AudioWorkletNode !== 'undefined'
    );
  }

  /** Ask for the microphone. Call from a user gesture. */
  async requestPermission(): Promise<MicPermission> {
    if (!MicCapture.supported()) {
      return 'unsupported';
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      return 'granted';
    } catch {
      return 'denied';
    }
  }

  /** Start streaming frames. requestPermission() must have succeeded. */
  async start(
    targetRate: number,
    onFrame: (pcm16: ArrayBuffer) => void,
    frameMs = 100
  ): Promise<void> {
    if (!this.stream) {
      throw new Error('microphone permission not granted');
    }
    this.context = new AudioContext();
    if (this.context.state === 'suspended') {
      await this.context.resume();
    }
    const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }));
    try {
      await this.context.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    this.node = new AudioWorkletNode(this.context, 'pcm-capture', {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      processorOptions: { targetRate, frameMs },
    });
    this.node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onFrame(e.data);
    this.source = this.context.createMediaStreamSource(this.stream);
    this.source.connect(this.node);
  }

  stop(): void {
    this.source?.disconnect();
    this.node?.disconnect();
    this.node?.port.close();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.context?.close();
    this.source = null;
    this.node = null;
    this.stream = null;
    this.context = null;
  }
}
