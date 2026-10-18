// Small grayscale previews stay in memory. No model calls or video uploads here.
export function frameDifference(a: Uint8Array, b: Uint8Array): number {
  if (a.length !== b.length || !a.length) return 255;
  let total = 0;
  for (let i = 0; i < a.length; i++) total += Math.abs(a[i] - b[i]);
  return total / a.length;
}

export class SceneTrigger {
  private previous: Uint8Array | null = null;
  private baseline: Uint8Array | null = null;
  private lastSent: Uint8Array | null = null;
  private changed = false;
  private movingAt = 0;
  private sentAt = -Infinity;

  reset(frame?: Uint8Array) {
    this.previous = frame?.slice() ?? null;
    this.baseline = frame?.slice() ?? null;
    this.changed = false;
    this.movingAt = 0;
  }

  submitted(frame: Uint8Array, now: number) {
    this.lastSent = frame.slice(); this.sentAt = now; this.reset(frame);
  }

  sample(frame: Uint8Array, now: number): boolean {
    if (!this.previous || !this.baseline) { this.reset(frame); return false; }
    if (frameDifference(frame, this.previous) > 8) this.movingAt = now;
    if (frameDifference(frame, this.baseline) > 12) {
      if (!this.changed) this.movingAt = now;
      this.changed = true;
    }
    this.previous = frame.slice();
    return this.changed && now - this.movingAt >= 1500 && now - this.sentAt >= 10000
      && (!this.lastSent || frameDifference(frame, this.lastSent) > 12);
  }
}
