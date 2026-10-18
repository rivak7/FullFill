# FullFill: technical notes

DubHacks 2026. How FullFill decides when to look, what it saw, and when an order is done, plus the bugs we hit getting it to work on a real mat.

## Pipeline

1. The cashier rings up an order on our order site. It becomes a Square order (Square Sandbox is both the order feed and our only storage).
2. The kitchen display (React, in the browser) pulls Square orders into a queue and runs the phone camera (iPhone over Continuity Camera, wired).
3. A motion trigger in the browser watches a 32×32 preview of the feed. When the mat settles with something new on it, it sends one still (scaled to 1024 px on the long side) to our API (FastAPI on Vercel).
4. The API sends Perceptron Mk1.5 the still plus reference photos: every item on the ticket, and up to 3 lookalikes (12 photos max). The prompt is a blind inventory. The model is never told what was ordered. It counts each listed item, or says it is unsure, and flags anything it can't name.
5. `compare_order` diffs those counts against the ticket and returns green, red or amber. The result is written back to the Square order's metadata.
6. A green order moves on after 1 to 2 s; a red one moves on when the mat is cleared. Nobody taps anything.

Two resolutions on purpose: 32×32 for "did something change", 1024 px for "what is it". Telling apart our two near-identical tofu bowls (same container, one has rice) needs the detailed photo. Deciding whether the mat moved doesn't.

## Motion trigger

Runs every 125 ms on a 32×32 RGB preview of the 1280×960 feed (each preview pixel averages about 40×30 camera pixels). No model calls.

Changed pixel: compare frame to a reference frame per pixel, per colour channel, after subtracting the median shift of each channel (removes whole-frame exposure changes). A pixel counts as changed if some channel is off by more than 25 and it also differs from all 8 neighbours in the reference (so a 1 px camera nudge doesn't light up every paper edge). Colour matters: mustard on brown cardboard has about the same brightness and a very different blue channel.

Thresholds: a sauce packet is 1 to 2 px at this size, so 2 changed px is "something is there". Still = no average change above 8 for 500 ms.

When to photograph: the mat has been still for 500 ms and differs from the last photo sent. A hand moving over the mat is never still, so it never triggers a check.

Empty mat: learned from the first settled frame after the camera starts (or after Start fresh). Everything about clearing depends on this frame.

When the order is done:

- After green: the queue moves on 2 s later whatever the mat shows, or as soon as the mat clears, but never sooner than 1 s, so the worker sees the green. The next order is only photographed once the mat clears and something new is placed. To tell it's clear, look only at the "order spots" (pixels where the passed photo differs from the empty mat). Fewer than 2 still differ, and 250 ms still, means cleared. Bagging can be messy everywhere else on the mat; only the order's own spots matter.
- Fallback: if the spots never match (mat moved, lighting changed), a changed mat that stays still for 4 s counts as cleared, and becomes the new empty mat.
- After red: if the whole mat matches the empty mat and is still, the worker bagged it anyway. That's their override: the ticket stays red and the queue moves on. Exception: a red where the model saw none of the order (every item missing, count 0) was a photo of a hand or a bare mat, so clearing it means nothing.
- After amber: never auto-advance. The model was unsure, and the next check often turns it green. The worker leaves by tapping.

## Verdict rules

All in `compare_order`. Perceptron reports, our code decides.

- Red: a ticket item is definitely short or over, or a known menu item that isn't on the ticket is on the mat. Red beats everything else.
- Amber: the model couldn't see, count or tell something apart, saw an object it can't name, or a line needs a manual check ("no rice"). Amber always says why, in one line.
- Green: every count matches and nothing above applies.
- Unsure, but its best count equals the ticket's quantity: counted as a match. In one evening's logs, 71 of 97 unsure item answers came with a count, almost all of them 1. Tradeoff: a lookalike swap with the right count can now pass.
- A scene note ("keep the order inside the frame") only shows next to another problem. Alone, it doesn't block green.
- A model answer that contradicts itself (calls an item missing and gives it a count) turns that item amber. It doesn't fail the whole check.
- One browser retry after an error. One recheck after amber. Green and red never refresh on a timer. Perceptron calls are capped at 1 per second.

## Problems and fixes

Roughly in the order we hit them.

1. Small items invisible to the trigger. First version averaged 8×8 blocks in grayscale. One packet barely moved the average, and mustard on cardboard was the same grey. Fix: per-pixel, full colour, 2 px threshold.
2. Mat swaps. White paper, cardboard, white paper again. White salt and pepper sachets on white paper changed almost no pixels and the model missed them too, so we dropped them from the demo menu. Every swap needs a fresh empty mat.
3. Perfect orders came back amber. The model flagged clutter around the mat (paper edge, cable, strap, grease) as a possible second order. Fix: prompt says the mat and anything around it are never items; a scene note alone can't block green.
4. Slow checks, 4 to 5 s. Per-step timings showed the model call at 3.6 s, growing with reference photos. We were sending nearly the whole menu as lookalikes. Fix: at most 3 lookalikes, drop a confirm round trip. Model call for a small order: 2.3 to 2.9 s.
5. Malformed answers threw away the whole check (one took 6.1 s and then failed) and turned auto-check off. Fix: contradictions become per-item amber, one retry, auto-check stays on.
6. Order never cleared. Opening the log tab hid the video, the browser paused it, and the trigger kept comparing against a frozen frame of the full order. Fix: camera stays visible as a thumbnail, and a paused preview restarts itself.
7. Clearing was slow. The original rule waited for a full scene change plus a settle. Fix: the order-spots test (250 ms), with the 4 s still fallback.
8. Workers had to tap to get past red or amber. Fix: bagging past a warning counts as an override.
9. Orders of 5+ items came back amber even when complete. We tried giving the model reasoning effort ("low" for 4+ items): slower, still hedged. Removed. Fix: a smaller, focused demo menu (one station's worth of items). Pushing items closer together also helped.
10. Amber kicked us off the order. The override test (#8) only looked at the order's spots, so lifting items while a hand or a new item sat elsewhere read as cleared. Fix: amber never auto-advances; red needs the whole mat bare.
11. Queue skipped every remaining order. Chain: the remembered empty mat went stale (lighting), so the green order took about 30 s to clear via the 4 s fallback (people kept moving, which restarted the timer). The next order was photographed within a second with a hand on the mat, came back red with everything missing, then the mat looked bare, which counted as "bagged past red". Same thing on each following order. Fix: a red that saw none of the order is not a bag.
12. Too many ambers from the model hedging on items it could see. Fix: trust an unsure count that matches the ticket.
13. Shadows and glare. We tried ignoring pixels where all three colours dim or brighten together. On white paper that also hid pale items (a white sauce cup changes every channel by about the same amount), so new orders stopped triggering. Removed.
14. Next order set down before the last one was cleared. A fix that checked those items right away, plus a longer 1 s settle, broke triggering during filming, so both were reverted. For now: clear the mat before setting down the next order.
15. Deploys failed. Each push to main deploys 3 Vercel apps, and we hit the free plan's 100 per day. Vercel's dashboard looked fine; the GitHub Actions log said "Resource is limited". Fix: Pro plan, re-run the job.
16. Green waited on the pixel test. Every stale-mat bug held a finished order on screen. Fix: green moves on after 2 s regardless (at least 1 s on screen); the pixel test now only gates the next photo.

## Designs we considered

- YOLO or another trained detector. Needs hundreds of labeled photos per item and a retrain per menu change, and can't read a handwritten label. A vision-language model with reference photos needs one photo per item. Later, Perceptron's checks could label data to train a small per-restaurant detector.
- Smoothing filter. The 32×32 downsample is already a heavy blur. A shadow is a large smooth region, so blurring keeps it. A lighting-tolerant test hid pale items on white paper, so we dropped it too. The model always gets the unblurred 1024 px photo, so nothing here costs detail.
- Model confirms the mat is empty (Roy). Use "no items seen" as cleared instead of pixels. Good for the stale-mat case: when the pixel test can't decide, one extra call settles it and relearns the mat. Fix #11 already uses half of this.
- Photograph every second, or send the next call as soon as the last returns (William, Roy). One call in flight avoids the rate limit, but a photo taken just before the order settles is stale, so worst case is two calls (about 8 s) instead of one (about 4.5 s). Mid-bagging photos flash red and amber unless two answers in a row must agree, which adds another call. Cleaner to explain, slower in practice. Deferred.
- Hierarchical recognition for big menus. Find objects, sort each into a category (sauce, drink, entrée), then pick the item from that category's few lookalikes, all in parallel. Each call stays small whatever the menu size. Main win is accuracy on big menus, not speed.
- Split the mat into regions, one call each. Same parallelism, but it doesn't shrink the menu each call has to search, and items on a boundary get counted twice or not at all.

## Limits

- One order on the mat at a time.
- Square only.
- Special requests go to amber for a person.
- Only the latest result per order is kept; no history.
- Can't see inside closed containers.
- Not yet measured on a proper test set, including how much reference photos help over names alone.
- Trusting unsure counts trades a little accuracy for fewer false ambers.
