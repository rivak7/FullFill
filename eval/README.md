# Go/no-go tests (T1-T3)

Real Perceptron Mk1.5 calls with a JSON schema answer, reasoning off, a cooldown between calls, and two hard caps: one per run (exactly the planned calls) and a lifetime cap across all eval runs (`EVAL_MAX_TOTAL_CALLS`, default 200, counted in `logs/eval/call_budget.json`). A run also stops after 3 failed calls in a row. Pass criteria are the ones in [order-checker.md](../order-checker.md#passfail-tests-decide-by-about-3-pm).

Run everything from the repo root on the Mac, on the phone hotspot, with the mount in its final position.

## 1. Key

The key is read from `PERCEPTRON_API_KEY`, either exported in the shell or in the untracked `.env`. Never commit it.

```sh
export PERCEPTRON_API_KEY=ak....
pip install -r requirements.txt
python -m unittest eval.test_eval     # offline, spends nothing
```

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

The expected quantities are not sent to the model, so it counts instead of agreeing with the ticket. The prompt is in `prompt_v1.txt`; if you change it, save it as `prompt_v2.txt` and point `PROMPT_FILE` in `vision.py` at it, so logged results stay comparable.

## Next step

Once the go/no-go passes, move the request code in `vision.py` behind `PerceptronVision.inspect(VisionInput)` in `apps/api/fullfill/adapters/vision/perceptron.py`, and have this runner call that adapter, so the eval and the app share one request path and the same `Observations`/`Comparison` types.
