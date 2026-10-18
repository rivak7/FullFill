# Go/no-go tests (T1-T3)

Real Perceptron Mk1.5 calls with a JSON schema answer, reasoning off, a cooldown between calls, and two hard caps: one per run (exactly the planned calls) and a lifetime cap across all eval runs (`EVAL_MAX_TOTAL_CALLS`, default 200, counted in `logs/eval/call_budget.json`). A run also stops after 3 failed calls in a row. Pass criteria are the ones in [order-checker.md](../order-checker.md#passfail-tests-decide-by-about-3-pm).

Run everything from the repo root on the Mac, on the phone hotspot, with the mount in its final position.

## 1. Key

The key is read from `PERCEPTRON_API_KEY`, either exported in the shell or in the untracked `.env`. Never commit it.

```sh
export PERCEPTRON_API_KEY=ak....
uv sync --inexact --all-packages --extra camera   # Python 3.13 + every package, incl. OpenCV
source .venv/bin/activate                         # once per terminal
python -m pytest eval/test_eval.py                # offline, spends nothing
```

With the venv active, every `python -m eval...` command below works as written. Without it, put `uv run --no-sync` in front, e.g. `uv run --no-sync python -m eval.live --fake`.

## Quick smoke test (3 calls)

Before T1, check that Perceptron sees one item and reads its marker label:

```sh
python -m eval.smoke path/to/burrito.png
```

It asks an open question with no hints, then runs the real order-check request for one chicken burrito marked C, then checks it against a lookalike steak burrito marked S. No reference photos or manifest needed.

## 2. Photos

```sh
# references: one folder per menu item id, 1-3 photos each
python -m eval.capture data/references/ranch_cup ref_
# test orders
python -m eval.capture eval/photos t2_
```

Space saves, q quits. Photos are gitignored. Take references and test photos from the same mount and lighting.

## 3. Manifest

Copy `eval/manifest.example.json` to `eval/manifest.json` and list the menu and every photo:

- `order`: what the ticket says, `{item_id: quantity}`.
- `actual`: what is really on the mat, when it differs (an error case). Leave it out for a correct order.
- `extras`: items on the mat that aren't on the ticket (the wrong drink in a swap).
- T3 cases need `kind`: `lookalike` (scored on exact counts) or `label` (with `labels`, the marker text to read).

T2 needs 20 error orders and 10 correct ones. T1 uses the first `t1` case; give it 5 items so the call carries 5 reference photos.

## 4. Run

```sh
python -m eval.run t2 --dry-run --mode both   # checks the manifest and photos, no calls
python -m eval.run ping                       # 1 call: key, model id and format work
python -m eval.run t1                         # 20 calls
python -m eval.run t2 --mode both             # 60 calls: names-plus-photos and names-only
python -m eval.run t3 --mode both
```

Each run prints PASS/FAIL per test, cost per check, input tokens per check, and which cases the reference photos fixed or broke compared with names only. Every call is logged to `logs/eval/<time>_<test>.jsonl`; `python -m eval.run summarize <log>` re-scores one without new calls.

A T2 error counts as caught when the screen would not show green (red, or amber for a human look). A false alarm is a correct order that isn't green. The red-only numbers are printed alongside.

The eval calls the app's own Perceptron adapter (`apps/api/fullfill/adapters/vision/perceptron.py`) and decision rules (`apps/api/fullfill/domain/compare_order.py`), with the same reference candidate selection. Camera timing and shared-order persistence are tested separately. The expected quantities are not sent to the model, so it counts instead of agreeing with the ticket. If you change the prompt there, bump `PROMPT_VERSION` so logged results stay comparable.

A menu item with `"label": ["C"]` must carry that readable label to count. A lookalike with no readable label comes back unsure, so the check shows amber.

## Website regression photo set

Use a small labeled set before enabling automatic checks in a real kitchen.
Include a correct order, a missing item, an extra known menu item, an unknown
object, a substitution between similar-looking menu items, a hidden filling,
a blurred frame, an occluded item, and two orders mixed together. For lookalikes,
include both readable and unreadable labels. Record what is actually visible;
do not label a hidden filling as visually knowable.

The photo mode now uses the website's candidate selector: all available menu
photos are ranked locally, with up to six alternative items sent alongside the
ordered references in the same request. Use one reference per item to match the
website. Include references for competing menu items, even if they are not on
the ticket. The selector is a retrieval heuristic, not a measured classifier.
The harness preserves wrong-item identity and whole-scene uncertainty in scoring.

Run the offline tests and manifest dry run first. Only run a live evaluation
when the photos are ready and the planned call count is acceptable. Automated
fake-provider tests verify software behavior; they do not establish camera
accuracy. Browser handoff, stale references, and simultaneous workers are tested
separately in `tests/` and `apps/web/tests/`.

## Live demo on the mount (no POS needed)

`python -m eval.live` runs the real loop: the camera trigger sends one photo each time the mat settles after a change, Perceptron checks it against a hardcoded ticket, and a window shows green, red or amber with the reasons. Start with the mat clear so it learns the empty mat.

```sh
cp eval/live_order.example.json eval/live_order.json    # edit the menu and the ticket
python -m eval.live --fake                               # no calls: checks the trigger and window
python -m eval.live --order chicken_burrito=1,ketchup=3  # real calls, capped at 50 per run
```

Keys: `r` drag a box around the mat, `e` re-learn the empty mat, `c` check now, `q` quit. Each check's photo and result go to `logs/live/`. Reference photos come from `data/references/<item_id>/` as above.
