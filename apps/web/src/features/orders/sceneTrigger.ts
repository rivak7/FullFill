// Small colour previews (32×32 RGB) stay in memory. No model calls or video uploads here.
// Frames are square: RGB triples, or single grey values (used by the tests).
function layout(length: number) {
  const channels = length % 3 === 0 && Number.isInteger(Math.sqrt(length / 3)) ? 3 : 1;
  return { channels, edge: Math.sqrt(length / channels) };
}

export function frameDifference(a: Uint8Array, b: Uint8Array): number {
  if (a.length !== b.length || !a.length) return 255;
  let total = 0;
  for (let i = 0; i < a.length; i++) total += Math.abs(a[i] - b[i]);
  let difference = total / a.length;
  const { channels, edge } = layout(a.length);
  if (!Number.isInteger(edge) || edge < 8) return difference;
  // Small packets should not disappear into an average of the whole counter.
  // Compare 4×4 regions as well, while averaging out individual noisy pixels.
  const tile = Math.ceil(edge / 4);
  for (let y = 0; y < edge; y += tile) for (let x = 0; x < edge; x += tile) {
    let sum = 0, count = 0;
    for (let row = y; row < Math.min(y + tile, edge); row++) for (let col = x; col < Math.min(x + tile, edge); col++)
      for (let c = 0; c < channels; c++) { const i = (row * edge + col) * channels + c; sum += Math.abs(a[i] - b[i]); count++; }
    difference = Math.max(difference, sum / count);
  }
  return difference;
}

// How long the mat must stay still before a photo is taken, and how often it is sampled.
export const SETTLE_MS = 500;
export const SAMPLE_MS = 125;
// A changed mat that stays still this long counts as cleared even if it doesn't match
// the learned bare mat (a swapped mat, new lighting, a crumb).
export const CLEARED_FALLBACK_MS = 4000;

// Pixels of `frame` that differ from `before` once a whole-frame exposure shift is
// removed. Colour counts, not just brightness: a mustard packet and brown cardboard are
// about as bright, but their blue channels are far apart. A pixel only counts if it
// differs from all of its neighbours in `before` too, so a phone nudged by a pixel
// doesn't light up every paper edge. A 32-px preview makes a sauce packet only a pixel
// or two, so the caller compares to 2.
export function changedPixels(frame: Uint8Array, before: Uint8Array, stopAt = Infinity): number {
  if (frame.length !== before.length || !frame.length) return Infinity;
  const { channels, edge } = layout(frame.length);
  const pixels = frame.length / channels;
  const shift = Array.from({ length: channels }, (_, c) =>
    Array.from({ length: pixels }, (_, p) => frame[p * channels + c] - before[p * channels + c]).sort((x, y) => x - y)[pixels >> 1]);
  const same = (p: number, q: number) => {
    for (let c = 0; c < channels; c++) if (Math.abs(frame[p * channels + c] - before[q * channels + c] - shift[c]) > 25) return false;
    return true;
  };
  const square = Number.isInteger(edge);
  let changed = 0;
  for (let p = 0; p < pixels; p++) {
    if (same(p, p)) continue;
    let moved = false;
    if (square) {
      const row = Math.floor(p / edge), col = p % edge;
      for (let y = Math.max(0, row - 1); y <= Math.min(edge - 1, row + 1) && !moved; y++)
        for (let x = Math.max(0, col - 1); x <= Math.min(edge - 1, col + 1); x++)
          if (same(p, y * edge + x)) { moved = true; break; }
    }
    if (!moved && ++changed >= stopAt) return changed;
  }
  return changed;
}

export function isEmptyMat(frame: Uint8Array, empty: Uint8Array): boolean {
  return changedPixels(frame, empty, 2) < 2;
}

// A real change to what is on the mat: a big average change, or a small object
// (one packet) that the averages in frameDifference wash out.
// Both directions: the neighbour tolerance in changedPixels hides a small object that
// was taken away (its old neighbours look like the bare mat), so check the old frame
// against the new one as well.
export function sceneChanged(frame: Uint8Array, before: Uint8Array): boolean {
  return frameDifference(frame, before) > 12 || changedPixels(frame, before, 2) >= 2 || changedPixels(before, frame, 2) >= 2;
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
    if (this.learning && settledFor >= SETTLE_MS) {
      this.learning = false;
      // The previous order is still on the mat; without a bare mat, fall back below.
      if (!this.handoffFrom || sceneChanged(frame, this.handoffFrom)) this.empty = frame.slice();
    }
    if (this.handoffFrom) {
      if (!this.betweenOrders) {
        // Observe a settled scene before accepting a second transition. With a learned
        // bare mat that scene must be the empty mat (small packets alone barely move the
        // averages, so this compares pixels); without one any settled change counts.
        const matches = this.empty ? isEmptyMat(frame, this.empty) : false;
        if (settledFor >= SETTLE_MS && sceneChanged(frame, this.handoffFrom)
          && (matches || !this.empty || settledFor >= CLEARED_FALLBACK_MS)) {
          // Follow slow lighting drift, and learn a whole new mat (most of the view
          // changed, e.g. cardboard swapped in for paper). A few leftover packets
          // don't replace the learned bare mat.
          if (matches || (this.empty && changedPixels(frame, this.empty) > frame.length / 4 / layout(frame.length).channels)) this.empty = frame.slice();
          this.betweenOrders = frame.slice();
          this.reset(frame);
        }
        return false;
      }
      // Do not spend a check on the intermediate/cleared view. Identical meals
      // can pass this gate after the observed removal-and-replacement sequence.
      return settledFor >= SETTLE_MS && sceneChanged(frame, this.betweenOrders);
    }
    return settledFor >= SETTLE_MS && (extraDue || this.retryPending || sceneChanged(frame, this.baseline))
      && (extraDue || !this.lastSent || sceneChanged(frame, this.lastSent));
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
