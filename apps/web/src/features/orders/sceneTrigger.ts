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

// Pixels that differ from the empty mat once a whole-frame exposure shift is removed.
// A 32-px preview makes a sauce packet only a pixel or two, so two pixels count.
export function isEmptyMat(frame: Uint8Array, empty: Uint8Array): boolean {
  if (frame.length !== empty.length) return false;
  const shift = Array.from(frame, (value, i) => value - empty[i]).sort((a, b) => a - b)[frame.length >> 1];
  let changed = 0;
  for (let i = 0; i < frame.length; i++) if (Math.abs(frame[i] - empty[i] - shift) > 25 && ++changed >= 2) return false;
  return true;
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
  private retryPending = false;
  // The bare mat, learned from the first settled scene after the camera opens (like
  // apps/capture's trigger). With it, an order only ends once the mat is empty again.
  private empty: Uint8Array | null = null;
  private learning = false;

  get handoff(): "remove" | "place" | null {
    return this.handoffFrom ? this.betweenOrders ? "place" : "remove" : null;
  }

  reset(frame?: Uint8Array) {
    this.previous = frame?.slice() ?? null;
    this.baseline = frame?.slice() ?? null;
    this.stableFrame = null;
    this.lastAt = null;
  }

  learnEmptyMat() {
    this.empty = null; this.learning = true;
  }

  nextOrder() {
    this.retryPending = false;
    // A checked order was on the "empty" mat, so it was learned with items on it.
    if (this.empty && this.lastSent && isEmptyMat(this.lastSent, this.empty)) this.empty = null;
    // Preserve an unfinished handoff through an empty queue or another selection.
    // A still frame from the previous ticket must never automatically check the next.
    this.handoffFrom ??= (this.lastSent ?? this.previous)?.slice() ?? null;
    // Nothing on the mat to clear: go straight to waiting for the next order.
    if (this.handoffFrom && !this.betweenOrders && this.empty && isEmptyMat(this.handoffFrom, this.empty)) this.betweenOrders = this.handoffFrom;
    this.lastSent = null;
    this.reset(this.previous ?? this.handoffFrom ?? undefined);
  }

  interrupt() {
    // A hidden/stopped camera cannot provide evidence of a physical handoff.
    this.betweenOrders = null;
    this.reset();
  }

  suspend() {
    // Keep the last scene baseline, but never count hidden time as stillness
    // or as evidence that the previous order was removed.
    this.previous = null;
    this.stableFrame = null;
    this.lastAt = null;
    this.betweenOrders = null;
  }

  retryInterrupted() {
    this.reset();
    this.lastSent = null;
    this.retryPending = true;
  }

  submitted(frame: Uint8Array) {
    this.retryPending = false;
    this.handoffFrom = null; this.betweenOrders = null;
    this.lastSent = frame.slice(); this.reset(frame);
  }

  sample(frame: Uint8Array, now: number, extraDue = false): boolean {
    if (this.lastAt !== null && now - this.lastAt > 1000) this.interrupt();
    this.lastAt = now;
    this.previous ??= frame.slice();
    this.baseline ??= frame.slice();
    if (!this.stableFrame || frameDifference(frame, this.previous) > 8
      || frameDifference(frame, this.stableFrame) > 8) {
      this.stableFrame = frame.slice(); this.stableSince = now;
    }
    this.previous = frame.slice();
    const settledFor = now - this.stableSince;
    if (this.learning && settledFor >= 750) {
      this.learning = false;
      // The previous order is still on the mat; without a bare mat, fall back below.
      if (!this.handoffFrom || frameDifference(frame, this.handoffFrom) > 12) this.empty = frame.slice();
    }
    if (this.handoffFrom) {
      if (!this.betweenOrders) {
        // Observe a changed scene for 750 ms before accepting a second transition.
        // With a learned bare mat that scene must be the empty mat; without one this
        // is only a heuristic for removal.
        if (frameDifference(frame, this.handoffFrom) > 12 && settledFor >= 750
          && (!this.empty || isEmptyMat(frame, this.empty))) {
          if (this.empty) this.empty = frame.slice(); // follow slow lighting drift
          this.betweenOrders = frame.slice();
          this.reset(frame);
        }
        return false;
      }
      // Do not spend a check on the intermediate/cleared view. Identical meals
      // can pass this gate after the observed removal-and-replacement sequence.
      return frameDifference(frame, this.betweenOrders) > 12 && settledFor >= 750;
    }
    return (extraDue || this.retryPending || frameDifference(frame, this.baseline) > 12) && settledFor >= 750
      && (extraDue || !this.lastSent || frameDifference(frame, this.lastSent) > 12);
  }
}

// A result describes the photo that was sent, so movement after capture never revokes
// it (docs/system-design.md: bagging must not invalidate the evidence). Items added
// while the check runs start a new check once the mat settles. Only events that break
// the link between the photo and this ticket or screen invalidate the result.
export class SceneGuard {
  private invalidReason: string | null = null;
  get reason() { return this.invalidReason; }
  invalidate(reason: string) { this.invalidReason ??= reason; }
  unchanged() { return this.invalidReason === null; }
}
