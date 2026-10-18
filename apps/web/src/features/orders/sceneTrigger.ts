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
  private handoffFrom: Uint8Array | null = null;
  private betweenOrders: Uint8Array | null = null;
  private stableFrame: Uint8Array | null = null;
  private stableSince = 0;
  private lastAt: number | null = null;

  get handoff(): "remove" | "place" | null {
    return this.handoffFrom ? this.betweenOrders ? "place" : "remove" : null;
  }

  reset(frame?: Uint8Array) {
    this.previous = frame?.slice() ?? null;
    this.baseline = frame?.slice() ?? null;
    this.stableFrame = null;
    this.lastAt = null;
  }

  nextOrder() {
    // Preserve an unfinished handoff through an empty queue or another selection.
    // A still frame from the previous ticket must never automatically check the next.
    this.handoffFrom ??= (this.lastSent ?? this.previous)?.slice() ?? null;
    this.lastSent = null;
    this.reset(this.previous ?? this.handoffFrom ?? undefined);
  }

  interrupt() {
    // A hidden/stopped camera cannot provide evidence of a physical handoff.
    this.betweenOrders = null;
    this.reset();
  }

  submitted(frame: Uint8Array) {
    this.handoffFrom = null; this.betweenOrders = null;
    this.lastSent = frame.slice(); this.reset(frame);
  }

  sample(frame: Uint8Array, now: number): boolean {
    if (this.lastAt !== null && now - this.lastAt > 1000) this.interrupt();
    this.lastAt = now;
    if (!this.previous || !this.baseline) {
      this.previous = frame.slice(); this.baseline = frame.slice();
    }
    if (!this.stableFrame || frameDifference(frame, this.previous) > 8
      || frameDifference(frame, this.stableFrame) > 8) {
      this.stableFrame = frame.slice(); this.stableSince = now;
    }
    this.previous = frame.slice();
    const settledFor = now - this.stableSince;
    if (this.handoffFrom) {
      if (!this.betweenOrders) {
        // Observe a changed intermediate scene for 750 ms before accepting a
        // second transition. This is a visual heuristic, not proof of emptiness.
        if (frameDifference(frame, this.handoffFrom) > 12 && settledFor >= 750) {
          this.betweenOrders = frame.slice();
          this.reset(frame);
        }
        return false;
      }
      // Do not spend a check on the intermediate/cleared view. Identical meals
      // can pass this gate after the observed removal-and-replacement sequence.
      return frameDifference(frame, this.betweenOrders) > 12 && settledFor >= 1500;
    }
    return frameDifference(frame, this.baseline) > 12 && settledFor >= 1500
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
