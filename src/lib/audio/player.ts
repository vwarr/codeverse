// Gapless playback of PCM16 chunks arriving over the socket.
//
// Chunks are scheduled back-to-back on the AudioContext clock. A small lead (`leadMs`) absorbs
// network jitter; flush() drops everything queued, which is how barge-in interrupts the interviewer.

export class PcmPlayer {
  private context: AudioContext;
  private nextTime = 0;
  private active = new Set<AudioBufferSourceNode>();
  private readonly leadSec: number;

  constructor(
    public readonly sampleRate: number,
    leadMs = 60
  ) {
    this.context = new AudioContext({ sampleRate });
    this.leadSec = leadMs / 1000;
  }

  async resume(): Promise<void> {
    if (this.context.state === 'suspended') {
      await this.context.resume();
    }
  }

  get playing(): boolean {
    return this.active.size > 0;
  }

  enqueue(pcm16: ArrayBuffer): void {
    const samples = new Int16Array(pcm16);
    if (samples.length === 0) {
      return;
    }
    const buffer = this.context.createBuffer(1, samples.length, this.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) {
      data[i] = samples[i] / 0x8000;
    }
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const now = this.context.currentTime;
    if (this.nextTime < now + 0.005) {
      this.nextTime = now + this.leadSec; // (re)start the stream with a small lead
    }
    source.start(this.nextTime);
    this.nextTime += buffer.duration;
    this.active.add(source);
    source.onended = () => this.active.delete(source);
  }

  /** Drop everything scheduled but not yet heard. */
  flush(): void {
    for (const s of this.active) {
      try {
        s.stop();
      } catch {
        // already stopped
      }
    }
    this.active.clear();
    this.nextTime = 0;
  }

  close(): void {
    this.flush();
    void this.context.close();
  }
}
