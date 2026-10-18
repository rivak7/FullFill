// Small grayscale previews stay in memory. No model calls or video uploads here.
export function frameDifference(a: Uint8Array, b: Uint8Array): number {
  if (a.length !== b.length || !a.length) return 255;
  let total = 0;
  for (let i = 0; i < a.length; i++) total += Math.abs(a[i] - b[i]);
  let difference = total / a.length;
  const edge = Math.sqrt(a.length);
  if (!Number.isInteger(edge) || edge < 8) return difference;
  // Small packets should not disappear into an average of the whole counter.
  // Compare 4×4 regions as well, while averaging out individual noisy pixels.
  const tile = Math.ceil(edge / 4);
  for (let y = 0; y < edge; y += tile) for (let x = 0; x < edge; x += tile) {
    let sum = 0, count = 0;
    for (let row = y; row < Math.min(y + tile, edge); row++) for (let col = x; col < Math.min(x + tile, edge); col++) {
      sum += Math.abs(a[row * edge + col] - b[row * edge + col]); count++;
    }
    difference = Math.max(difference, sum / count);
  }
  return difference;
}

export class SceneTrigger {
  private previous: Uint8Array | null = null;
  private baseline: Uint8Array | null = null;
  private lastSent: Uint8Array | null = null;
  private changed = false;
  private movingAt = 0;

  reset(frame?: Uint8Array) {
    this.previous = frame?.slice() ?? null;
    this.baseline = frame?.slice() ?? null;
    this.changed = false;
    this.movingAt = 0;
  }

  nextOrder() {
    // Identical meals on different tickets are separate checks. Still require
    // movement after selection so untouched food is not immediately reused.
    this.lastSent = null; this.reset();
  }

  submitted(frame: Uint8Array) {
    this.lastSent = frame.slice(); this.reset(frame);
  }

  sample(frame: Uint8Array, now: number): boolean {
    if (!this.previous || !this.baseline) { this.reset(frame); return false; }
    if (frameDifference(frame, this.previous) > 8) this.movingAt = now;
    if (frameDifference(frame, this.baseline) > 12) {
      if (!this.changed) this.movingAt = now;
      this.changed = true;
    }
    this.previous = frame.slice();
    return this.changed && now - this.movingAt >= 1500
      && (!this.lastSent || frameDifference(frame, this.lastSent) > 12);
  }
}

// A sticky guard: removing and replacing food still invalidates the captured photo.
export class SceneGuard {
  private dirty = false;
  private lastAt: number;
  constructor(private captured: Uint8Array, now: number) { this.lastAt = now; }
  invalidate() { this.dirty = true; }
  sample(frame: Uint8Array, now: number) {
    if (now - this.lastAt > 1000 || frameDifference(frame, this.captured) > 8) this.dirty = true;
    this.lastAt = now;
  }
  unchanged(now: number) { return !this.dirty && now - this.lastAt <= 1000; }
}
