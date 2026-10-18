"""Perceptron Mk1.5 adapter: one call per check, a strict JSON schema answer.

The order photo goes last, after one labeled reference photo set per target. Expected
quantities are never sent, so the model counts what it sees instead of agreeing with
the ticket. Verdicts are not decided here; see ``fullfill.domain.compare_order``.
"""

import asyncio
import base64
import json
import os
import re
import time

from fullfill_contracts.ports import VisionProvider
from fullfill_contracts.vision import (
    Observations,
    ProviderMetadata,
    TargetObservation,
    UnexpectedItem,
    VerificationTarget,
    VisionInput,
)

from fullfill.domain.vision_uncertainty import REASONS, SCENES

DEFAULT_MODEL = "perceptron-mk1.5"
PROMPT_VERSION = "order-check-v4-lookalikes"
STATUSES = ("present", "missing", "unsure")

PROMPT = """\
You check takeout orders at a restaurant packing station. A camera looks down at the \
packing area. The last image is the order photo. Any earlier images are labeled reference \
photos of this restaurant's own menu items. Some references are alternatives NOT ordered.

For each item in the list below, count how many of it are clearly visible in the order \
photo. Use the reference photos to tell similar-looking items apart (size, lid or can \
color, flavor printed on the top, packaging shape, printed or handwritten labels).

Rules:
- "scene_status": "clear" only when one entire order is visible and countable; otherwise \
"obscured", "blurry", "out_of_frame", or "mixed_orders". Empty, well-lit packing areas \
can be clear. A closed bag hiding the order is obscured, not empty.
- Report every listed item exactly once, using its id.
- status "present": you can identify at least one; "count" is a positive number.
- status "missing": you are confident none are there; "count" is 0.
- status "unsure": it may be hidden, cut off, blurry, or you cannot tell it apart from a \
similar item; "count" is your best guess or null.
- Never count one object for two different items.
- Do not infer fillings or flavors inside opaque packaging from the wrapper or a \
reference photo alone. If a readable label or visible contents do not distinguish \
lookalikes, use "unsure". Reference photos show appearance; they are not the order.
- "reason": "none" for a clear count; otherwise "visibility", "identity", "label", \
or "count". Missing means visibly absent, not merely hidden or hard to recognize.
- "label_text": the exact handwritten or printed text on that item's label, lid or \
wrapper, if readable; otherwise null.
- "unlabeled_count": for items marked LABEL REQUIRED, how many objects look like this \
item but have no readable label, so you can't tell which item they are. Do not include \
those in "count". For other items, 0.
- "unexpected_items": food or drink objects that match none of the ORDERED items. \
Report each with "name" (short description), "item_id" (an ALTERNATIVE reference id only \
when confidently identified, otherwise null), "count" (positive integer or null), \
"instead_of_target_id" (ordered target id only for a clear substitution, otherwise null), \
and "label_text" (exact readable text, otherwise null). Unidentified objects MUST use \
null item_id and null instead_of_target_id. Never force a match. An alternative's photo \
is comparison evidence, not a request to find it. LABEL REQUIRED alternatives need \
a matching readable name; never infer hidden ingredients. Ignore tickets, hands, and shadows.
- Do not decide whether the order is correct. Only report what you see.

ORDERED items to check:
{items}

ALTERNATIVE references (not ordered):
{alternatives}
"""


class VisionCallRejected(RuntimeError):
    """The spending guard refused a call; nothing was sent."""


class VisionProviderError(RuntimeError):
    """Perceptron failed or returned an answer that doesn't fit the request."""


class CallLimiter:
    """Cooldown between calls and a hard cap, so a misfiring trigger can't burn credits."""

    def __init__(self, max_calls: int, cooldown_s: float, clock=time.monotonic):
        self.max_calls = max_calls
        self.cooldown_s = cooldown_s
        self.calls = 0
        self._last: float | None = None
        self._clock = clock
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            if self.calls >= self.max_calls:
                raise VisionCallRejected(f"call cap of {self.max_calls} reached")
            if self._last is not None:
                wait = self.cooldown_s - (self._clock() - self._last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self.calls += 1
            self._last = self._clock()


def _data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def _target_line(target: VerificationTarget) -> str:
    line = f"- {target.target_id}: {target.name}"
    if target.verification_mode == "label":
        marks = " or ".join(f'"{alias}"' for alias in (target.label_aliases or [target.name]))
        line += f" (LABEL REQUIRED: only count it if marked {marks})"
    return line


def build_messages(request: VisionInput) -> list[dict]:
    # A base menu photo cannot demonstrate a ticket's specific modifications.
    names = {t.item_id: t.name.split(" — ", 1)[0] for t in request.targets}
    content: list[dict] = []
    for ref in request.references:
        label = (
            f"Reference photo of {ref.item_id} ({ref.name or names.get(ref.item_id, ref.item_id)}):"
        )
        content.append({"type": "text", "text": label})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _data_url(ref.image.data, ref.image.media_type)},
            }
        )
    content.append({"type": "text", "text": "Order photo:"})
    content.append(
        {
            "type": "image_url",
            "image_url": {"url": _data_url(request.image.data, request.image.media_type)},
        }
    )
    items = "\n".join(_target_line(t) for t in request.targets)
    content.append(
        {
            "type": "text",
            "text": PROMPT.format(
                items=items,
                alternatives="\n".join(
                    f"- {ref.item_id}: {ref.name or ref.item_id}"
                    + (" (LABEL REQUIRED)" if ref.verification_mode == "label" else "")
                    for ref in request.references
                    if ref.item_id not in names
                )
                or "None",
            ),
        }
    )
    return [{"role": "user", "content": content}]


def response_schema(target_ids: list[str], alternative_ids: list[str] | None = None) -> dict:
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["item_id", "status", "count", "label_text", "unlabeled_count", "reason"],
        "properties": {
            "item_id": {"type": "string", "enum": target_ids},
            "status": {"type": "string", "enum": list(STATUSES)},
            "count": {"type": ["integer", "null"], "minimum": 0, "maximum": 100000},
            "reason": {"type": "string", "enum": ["none", *REASONS]},
            "label_text": {"type": ["string", "null"]},
            "unlabeled_count": {"type": "integer", "minimum": 0},
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "order_check",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["items", "unexpected_items", "scene_status"],
                "properties": {
                    "items": {"type": "array", "items": item},
                    "unexpected_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "name",
                                "item_id",
                                "count",
                                "instead_of_target_id",
                                "label_text",
                            ],
                            "properties": {
                                "name": {"type": "string"},
                                "item_id": {
                                    "type": ["string", "null"],
                                    "enum": [*(alternative_ids or []), None],
                                },
                                "count": {
                                    "type": ["integer", "null"],
                                    "minimum": 1,
                                    "maximum": 100000,
                                },
                                "instead_of_target_id": {
                                    "type": ["string", "null"],
                                    "enum": [*target_ids, None],
                                },
                                "label_text": {"type": ["string", "null"]},
                            },
                        },
                    },
                    "scene_status": {"type": "string", "enum": list(SCENES)},
                },
            },
        },
    }


def parse_answer(
    text: str, request: VisionInput
) -> tuple[list[TargetObservation], list[UnexpectedItem]]:
    """Validate the model's JSON against the requested targets. Raises VisionProviderError."""
    try:
        data = json.loads(text)
        entries = data["items"]
        unexpected = data["unexpected_items"]
        scene = data.get("scene_status", "clear")  # Older offline evaluation fixtures.
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ValueError("items must be objects")
        if not isinstance(unexpected, list):
            raise ValueError("unexpected items must be a list")
        if not isinstance(scene, str) or scene not in SCENES:
            raise ValueError("invalid scene status")
    except (ValueError, KeyError, TypeError) as exc:
        raise VisionProviderError(f"answer is not the requested JSON: {exc}") from exc
    targets = {t.target_id: t for t in request.targets}
    seen: dict[str, TargetObservation] = {}
    for entry in entries:
        target_id = entry.get("item_id")
        if not isinstance(target_id, str) or target_id not in targets:
            raise VisionProviderError(f"unknown item_id {target_id!r}")
        if target_id in seen:
            raise VisionProviderError(f"duplicate item_id {target_id!r}")
        status, count = entry.get("status"), entry.get("count")
        if status not in STATUSES:
            raise VisionProviderError(f"bad status {status!r} for {target_id}")
        if count is not None and (type(count) is not int or not 0 <= count <= 100000):
            raise VisionProviderError(f"bad count {count!r} for {target_id}")
        if (status == "missing" and count != 0) or (status == "present" and count == 0):
            raise VisionProviderError("inconsistent status and count")
        reason_key = entry.get("reason", "unknown" if status == "unsure" else "none")
        if not isinstance(reason_key, str) or reason_key not in ("none", *REASONS):
            raise VisionProviderError("invalid uncertainty reason")
        reason = REASONS.get(reason_key)
        unlabeled = entry.get("unlabeled_count", 0)
        label = entry.get("label_text")
        if type(unlabeled) is not int or not 0 <= unlabeled <= 100000:
            raise VisionProviderError("invalid unlabeled count")
        if label is not None and not isinstance(label, str):
            raise VisionProviderError("invalid label text")
        target = targets[target_id]
        label_matches = bool(label and label.strip()) and (
            any(
                re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", label, re.I)
                for alias in (target.label_aliases or [target.name])
            )
        )
        if target.verification_mode == "label" and (
            unlabeled > 0 or (status == "present" and not label_matches)
        ):
            # An unlabeled lookalike might be this item: let the worker decide.
            status = "unsure"
            reason = REASONS["label"]
        elif reason or count is None:
            status = "unsure"
            reason = reason or REASONS["count"]
        if scene != "clear":
            status, reason = "unsure", SCENES[scene]
        seen[target_id] = TargetObservation(
            target_id=target_id,
            status=status,
            observed_quantity=count,
            reason=reason,
            label_text=label,
        )
    missing = sorted(set(targets) - set(seen))
    if missing:
        raise VisionProviderError(f"answer left out {missing}")
    alternatives = {
        ref.item_id: ref
        for ref in request.references
        if ref.item_id not in {target.item_id for target in request.targets}
    }
    extras = []
    for item in unexpected:
        # Preserve old offline fixtures as unidentified observations.
        if isinstance(item, str) and item.strip():
            extras.append(UnexpectedItem(name=item.strip()))
            continue
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
        ):
            raise VisionProviderError("invalid unexpected item")
        identity, replacement, count, label = (
            item.get(key) for key in ("item_id", "instead_of_target_id", "count", "label_text")
        )
        if (
            (
                identity is not None
                and (not isinstance(identity, str) or identity not in alternatives)
            )
            or (
                replacement is not None
                and (not isinstance(replacement, str) or replacement not in targets)
            )
            or (count is not None and (type(count) is not int or not 1 <= count <= 100000))
            or (label is not None and not isinstance(label, str))
        ):
            raise VisionProviderError("invalid unexpected item identity or count")
        reference = alternatives.get(identity)
        if (
            reference
            and reference.verification_mode == "label"
            and not (
                label
                and re.search(
                    r"(?<!\w)" + re.escape(reference.name or reference.item_id) + r"(?!\w)",
                    label,
                    re.I,
                )
            )
        ):
            identity, replacement = None, None
        if identity is None:
            replacement = None
        extras.append(
            UnexpectedItem(
                name=(reference.name or reference.item_id) if identity else item["name"].strip(),
                item_id=identity,
                instead_of_target_id=replacement,
                quantity=count,
            )
        )
    return [seen[t.target_id] for t in request.targets], extras


class PerceptronVision(VisionProvider):
    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        max_output_tokens: int = 300,
        timeout_s: float = 30.0,
        limiter: CallLimiter | None = None,
        client=None,
    ):
        """``client`` is for tests; otherwise a Perceptron ``AsyncClient`` is built from the key."""
        self.model = model or os.getenv("PERCEPTRON_MODEL") or DEFAULT_MODEL
        self.max_output_tokens = max_output_tokens
        # Optional limits are for explicitly budgeted offline evaluations only.
        self.limiter = limiter
        if client is None:
            from perceptron import AsyncClient

            key = api_key or os.getenv("PERCEPTRON_API_KEY")
            if not key:
                raise ValueError("PERCEPTRON_API_KEY is not set")
            client = AsyncClient(api_key=key, timeout=timeout_s)
        self._client = client

    async def inspect(self, request: VisionInput) -> Observations:
        if not request.targets:
            raise ValueError("a check needs at least one target")
        target_ids = [t.target_id for t in request.targets]
        messages = build_messages(request)
        if self.limiter is not None:
            await self.limiter.acquire()
        start = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=response_schema(
                    target_ids,
                    [
                        ref.item_id
                        for ref in request.references
                        if ref.item_id not in {target.item_id for target in request.targets}
                    ],
                ),
                max_completion_tokens=self.max_output_tokens,
                temperature=0,
                reasoning_effort="none",
            )
        except Exception as exc:  # SDK errors carry no secrets; keep the type for logs
            raise VisionProviderError(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = round((time.perf_counter() - start) * 1000)
        if completion.finish_reason != "stop":
            raise VisionProviderError(
                f"incomplete answer: finish_reason={completion.finish_reason}"
            )
        observations, unexpected = parse_answer(completion.text or "", request)
        answer = json.loads(completion.text)
        if "scene_status" not in answer:
            raise VisionProviderError("answer left out scene status")
        usage = completion.usage
        return Observations(
            capture_id=request.capture_id,
            targets=observations,
            unexpected_items=unexpected,
            scene_uncertainty=SCENES[answer["scene_status"]],
            provider=ProviderMetadata(
                provider="perceptron",
                model=self.model,
                prompt_version=PROMPT_VERSION,
                latency_ms=latency_ms,
                request_id=getattr(completion, "request_id", None),
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            ),
        )
