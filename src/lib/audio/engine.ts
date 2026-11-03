import { MicCapture, MicPermission } from './capture';
import { PcmPlayer } from './player';

/** Owns the mic and the speaker for one interview. Created from a user gesture (the Start click). */
export class AudioEngine {
  private mic = new MicCapture();
  private player: PcmPlayer | null = null;
  private muted = false;

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
    // Muted: drop the frames here too, so nothing reaches the interviewer even if the browser
    // ignores track.enabled.
    await this.mic.start(inputRate, (frame) => {
      if (!this.muted) {
        onFrame(frame);
      }
    });
  }

  play(pcm16: ArrayBuffer): void {
    this.player?.enqueue(pcm16);
  }

  get isMuted(): boolean {
    return this.muted;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.mic.setMuted(muted);
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
