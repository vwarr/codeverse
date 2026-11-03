// Builds the interview transcript from Gemini Live's streamed transcription events.
//
// The Live API sends the user's speech (`inputTranscription`) "independently of the other server
// messages and there is no guaranteed ordering" (https://ai.google.dev/api/live, now served at
// https://aistudio.google.com/api-reference/live#BidiGenerateContentServerContent). The user's words
// can arrive after the interviewer's reply has started, or even after it is complete. So the
// transcript cannot be built in arrival order:
//
// - The interviewer's speech (`outputTranscription`) joins the open interviewer entry. The entry
//   opens on the model's first output and stops taking text on `generationComplete` or
//   `interrupted` (the docs say the last output transcription comes before those, and
//   `turnComplete` follows).
// - The user's speech joins the open user entry. That entry stays open while the reply it caused
//   is generated, and after `turnComplete` until the reply has played (estimated from its audio)
//   plus a short grace, so that late words still go in front of the reply. The candidate cannot
//   answer a reply they have not heard. (A barge-in during the last of the playback, after
//   `turnComplete`, gets no `interrupted`, so its words join the earlier user line.) If the reply starts before any of the user's words arrive, the late
//   words go into a new entry in front of the reply.
// - `interrupted` (barge-in) closes both entries: the words that follow are a new user turn.
// - A transcription with `finished: true` closes the user entry at once.
// - The opening turn answers a hidden instruction, so no user entry goes in front of it. The
//   hidden opening and wrap-up instructions are text, which the Live API does not transcribe, so
//   they never show as user lines.
// - After a tool call, the model's next output continues the same interviewer entry.

import type { TranscriptTurn } from '../types';

/** A transcript line for the live view; `partial` while more text is still expected. */
export interface LiveTranscriptTurn extends TranscriptTurn {
  partial?: boolean;
}

/** How long after `turnComplete` (or the reply's playback end) late user words still join the turn. */
export const LATE_INPUT_GRACE_S = 1.0;

interface Entry {
  role: TranscriptTurn['role'];
  raw: string;
  t: number; // seconds since the interview started, when the entry began
}

/** Join two streamed fragments: keep the server's spacing, add a space only at a missing join. */
function join(prev: string, frag: string, newSegment: boolean): string {
  if (!prev) {
    return frag;
  }
  if (newSegment && !/\s$/.test(prev) && !/^[\s.,!?;:)\]}'"]/.test(frag)) {
    return `${prev} ${frag}`;
  }
  return prev + frag;
}

/** One line of text: single spaces, and a space after a sentence end that runs into a new one. */
export function cleanText(raw: string): string {
  return raw
    .replace(/\s+/g, ' ')
    .replace(/([a-z][.?!])(?=[A-Z])/g, '$1 ')
    .trim();
}

export class TranscriptBuilder {
  private entries: Entry[] = [];
  // The user entry that takes the user's speech.
  private user: Entry | null = null;
  // With no user entry: the interviewer entry that late user speech goes in front of.
  private userBefore: Entry | null = null;
  // After this time the user's speech starts a new entry (null: no deadline yet).
  private userUntil: number | null = null;
  // The interviewer entry that takes the model's speech.
  private model: Entry | null = null;
  // A model turn is in progress (between its first output and turnComplete / interrupted).
  private modelActive = false;
  // The next model output continues the last interviewer entry (a tool call ran in between).
  private continueModel = false;
  // The next model turn answers the hidden opening instruction.
  private opening = false;
  // The next text appended to the interviewer entry starts a new generation segment.
  private modelSegment = false;
  private version = 0;

  /** Bumped on every change, so the caller can tell when to publish. */
  get changes(): number {
    return this.version;
  }

  /** The hidden opening instruction was sent: the next model turn has no user turn before it. */
  openingSent() {
    this.opening = true;
  }

  /**
   * User speech. Returns true when it started a new user turn (not late words of an earlier one).
   */
  input(text: string, now: number, finished = false): boolean {
    this.expireUser(now);
    let isNew = false;
    if (text) {
      if (!this.user) {
        const entry: Entry = { role: 'candidate', raw: '', t: now };
        const at = this.userBefore ? this.entries.indexOf(this.userBefore) : -1;
        if (at >= 0) {
          entry.t = Math.min(now, this.userBefore!.t);
          this.entries.splice(at, 0, entry);
        } else {
          this.entries.push(entry);
          this.userUntil = null;
          this.continueModel = false;
          isNew = true;
        }
        this.user = entry;
        this.userBefore = null;
      }
      this.user.raw = join(this.user.raw, text, false);
      this.version++;
    }
    if (finished) {
      this.closeUser();
    }
    return isNew;
  }

  /** Model output (audio, transcription or a tool call): opens the model turn if needed. */
  modelOutput(now: number) {
    if (this.modelActive) {
      return;
    }
    this.modelActive = true;
    this.expireUser(now);
    // Open the interviewer entry now, so that it keeps its place if the user speaks over it.
    const entry = this.openModelEntry(now);
    if (this.opening) {
      this.opening = false;
      this.closeUser();
    } else {
      if (!this.user) {
        this.userBefore = entry;
      }
      // The user's late words keep joining their entry while this reply is generated.
      this.userUntil = null;
    }
  }

  /** Interviewer speech. */
  output(text: string, now: number) {
    this.modelOutput(now);
    if (!text) {
      return;
    }
    const entry = this.openModelEntry(now);
    entry.raw = join(entry.raw, text, this.modelSegment);
    this.modelSegment = false;
    this.version++;
  }

  /** A tool call: the model's next output continues the same interviewer entry. */
  toolCall(now: number) {
    this.modelOutput(now);
    this.continueModel = true;
  }

  /** `generationComplete`: no more interviewer text in this turn. */
  generationComplete() {
    this.closeModel();
  }

  /**
   * `turnComplete`: the model turn is over. Late user words join the turn before the reply until
   * `playedBy` (when the reply's audio has played) or `now`, plus the grace period.
   */
  turnComplete(now: number, playedBy = 0) {
    this.closeModel();
    if (!this.modelActive) {
      return;
    }
    this.modelActive = false;
    this.version++;
    if (this.user || this.userBefore) {
      this.userUntil = Math.max(now, playedBy) + LATE_INPUT_GRACE_S;
    }
  }

  /** `interrupted` (barge-in): the reply stops, and the user's next words are a new turn. */
  interrupted() {
    this.closeModel();
    this.modelActive = false;
    this.continueModel = false;
    this.closeUser();
    this.version++;
  }

  /** The connection closed: the turn in progress will not finish. */
  connectionLost(now: number) {
    this.turnComplete(now);
    this.continueModel = false;
  }

  /** Something was said. */
  hasContent(): boolean {
    return this.entries.some((e) => cleanText(e.raw));
  }

  /** The live view: every line in order, with the ones still taking text marked partial. */
  view(): LiveTranscriptTurn[] {
    return this.lines((e) => e === this.model || (e === this.user && !this.modelActive));
  }

  /** The final transcript, for the report. */
  final(): TranscriptTurn[] {
    return this.lines(() => false).map(({ role, text, t }) => ({ role, text, t }));
  }

  private lines(partial: (e: Entry) => boolean): LiveTranscriptTurn[] {
    const out: LiveTranscriptTurn[] = [];
    for (const e of this.entries) {
      const text = cleanText(e.raw);
      if (text) {
        const line: LiveTranscriptTurn = { role: e.role, text, t: Math.round(e.t * 100) / 100 };
        if (partial(e)) {
          line.partial = true;
        }
        out.push(line);
      }
    }
    return out;
  }

  private openModelEntry(now: number): Entry {
    if (this.model) {
      return this.model;
    }
    const last = this.entries.at(-1);
    if (this.continueModel && last?.role === 'interviewer') {
      this.model = last;
      this.modelSegment = true;
    } else {
      this.model = { role: 'interviewer', raw: '', t: now };
      this.entries.push(this.model);
    }
    this.continueModel = false;
    return this.model;
  }

  private closeModel() {
    if (this.model) {
      this.model = null;
      this.version++;
    }
  }

  private closeUser() {
    this.user = null;
    this.userBefore = null;
    this.userUntil = null;
  }

  private expireUser(now: number) {
    if (this.userUntil != null && now > this.userUntil) {
      this.closeUser();
    }
  }
}
