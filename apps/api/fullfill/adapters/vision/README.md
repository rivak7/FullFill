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
- No default spending cap or cooldown. The website uses one in-flight check per ticket and idempotency. Offline evaluation callers can explicitly pass `limiter=CallLimiter(...)` when running a budgeted experiment.

## Screen states

`Comparison.verdict` maps to the station screen:

| verdict | screen | when |
| --- | --- | --- |
| `pass` | green, order fulfilled | every item's count matches and nothing is uncertain |
| `fail` | red, order unfulfilled | something is definitely missing or there are too many of an item. Red wins even if something else is uncertain. |
| `unsure` | amber, worker decides | an item the model couldn't see or tell apart, an unlabeled lookalike, or something not on the ticket |

Each entry in `Comparison.discrepancies` has a ready-to-show `message`: "Missing: 1 Ketchup packet", "Extra: 1 Mayo packet", "Check Chicken burrito: 1 unlabeled item(s) look like Chicken burrito", or "Not on the ticket: Celsius can". Its `kind` is `missing`, `unexpected` or `unsure`, and `target_id` is the item id (empty for something not on the ticket).

## Label-only items (the unlabeled burrito)

Give a menu item `verification_mode="label"` and `label_aliases=["C"]`. The model then counts it only when it can read that label. If a burrito-shaped item has no readable label, that target comes back `unsure` with a reason, and the screen shows amber so the worker decides. `TargetObservation.label_text` holds whatever text the model read, for display.

## Per-call metadata

`Observations.provider` records the model, prompt version, latency in ms, and token counts for logging and cost. At Mk1.5 list prices a check costs about $0.0005.
