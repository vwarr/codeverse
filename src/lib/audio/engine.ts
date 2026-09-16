import { MicCapture, MicPermission } from './capture';
import { PcmPlayer } from './player';

/** Owns the mic and the speaker for one interview. Created from a user gesture (the Start click). */
export class AudioEngine {
  private mic = new MicCapture();
  private player: PcmPlayer | null = null;

  requestMic(): Promise<MicPermission> {
    return this.mic.requestPermission();
  }

  async start(
    inputRate: number,
    outputRate: number,
    onFrame: (pcm16: ArrayBuffer) => void
  ): Promise<void> {
    this.player = new PcmPlayer(outputRate);
    await this.player.resume();
    await this.mic.start(inputRate, onFrame);
  }

  play(pcm16: ArrayBuffer): void {
    this.player?.enqueue(pcm16);
  }

  interrupt(): void {
    this.player?.flush();
  }

  stop(): void {
    this.mic.stop();
    this.player?.close();
    this.player = null;
  }
}
