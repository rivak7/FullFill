# Vision adapter: what a check returns

One check is one Perceptron Mk1.5 call: the order photo plus reference photos for only the items on that ticket, answered in a strict JSON schema with reasoning off. Expected quantities are never sent to the model, so it counts what it sees.

## Calling it

```python
from fullfill.adapters.vision.perceptron import PerceptronVision
from fullfill.domain.compare_order import compare_order, targets_for

# Reads PERCEPTRON_API_KEY (and optional PERCEPTRON_MODEL) from the environment.
vision = PerceptronVision()
request = VisionInput(
    capture_id=...,
    image=ImageInput(jpeg_bytes, "image/jpeg"),
    targets=targets_for(order, menu),
    references=(...),
)
observations = await vision.inspect(request)  # fullfill_contracts.vision.Observations
comparison = compare_order(order, observations)  # fullfill_contracts.checks.Comparison
```

- Send an image that is already cropped to the mat and downscaled to about 1024 px. The adapter doesn't resize.
- `inspect` raises `VisionProviderError` when Perceptron fails or answers out of format, and `VisionCallRejected` when the spending guard refuses the call. Show either one as a failed check. Never show it as green.
- Rate limit: the website's checks share one `CallLimiter` that starts at most one Perceptron call per second per API process (`apps/api/fullfill/http/checks.py`); a call that arrives early waits instead of failing. There is no total cap. Offline evaluation callers can pass their own `limiter=CallLimiter(...)`.

## Screen states

`Comparison.verdict` maps to the station screen:

| verdict | screen | when |
| --- | --- | --- |
| `pass` | green, order fulfilled | every item's count matches and nothing below applies |
| `fail` | red, order unfulfilled | a ticket item is definitely short or over, or a known menu item that isn't on the ticket is there. Red wins even if something else is uncertain or the view is poor. |
| `unsure` | amber, worker decides | an item the model couldn't see, count or tell apart, an unlabeled lookalike, an object it can't identify, a line needing manual review, or a poor view of the scene |

These follow the comparison rules in `docs/system-design.md`. `compare_order` is the only place they live. The adapter, Square storage and the screens report or display its verdict; they never re-decide it.

Each entry in `Comparison.discrepancies` has a ready-to-show `message`: "Missing: 1 Ketchup packet", "Extra: 1 Mayo packet", "Check Chicken burrito: …", "Wrong item: expected TSSS; detected TSSSS" (a swap, red because TSSS is missing), "Wrong item: Mayo packet is not on this ticket" (red), or "Unidentified item: can" (amber). Its `kind` is `missing`, `unexpected`, `wrong_item`, `unidentified` or `unsure`.

## Label-only items (the unlabeled burrito)

Give a menu item `verification_mode="label"` and `label_aliases=["C"]`. The model then counts it only when it can read that label. If a burrito-shaped item has no readable label, that target comes back `unsure` with a reason, and the screen shows amber so the worker decides. `TargetObservation.label_text` holds whatever text the model read, for display.

## Per-call metadata

`Observations.provider` records the model, prompt version, latency in ms, and token counts for logging and cost. At Mk1.5 list prices a check costs about $0.0005.
