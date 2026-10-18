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
    BoundingBox,
    Observations,
    ProviderMetadata,
    TargetObservation,
    UnexpectedItem,
    VerificationTarget,
    VisionInput,
)

from fullfill.domain.vision_uncertainty import REASONS, SCENES

DEFAULT_MODEL = "perceptron-mk1.5"
PROMPT_VERSION = "order-check-v9-full-frame"
STATUSES = ("present", "missing", "unsure")

PROMPT = """\
You take inventory at a restaurant packing station. A camera looks down at the packing \
area. The last image is the order photo. Any earlier images are labeled reference photos \
of this restaurant's own menu items.

For each menu item in the list below, count how many of it are clearly visible in the \
order photo. The list is not the order: any of these items may or may not be there, so \
judge each object only by what it looks like. Use the reference photos to tell \
similar-looking items apart (size, lid or can color, toppings, flavor printed on the \
top, packaging shape, printed or handwritten labels).

Rules:
- Inspect the entire LAST image. Count food and drink anywhere in the camera frame, \
including outside a paper/cardboard mat, near its edges, or on the surrounding counter. \
The mat is background, never a boundary that excludes an item.
- "scene_status": "clear" when every food or drink object in the frame is visible and countable, \
even if items from the list are absent; otherwise "obscured", "blurry", "out_of_frame" \
(an object is cut off at the image edge), or "mixed_orders". Absent items are not a \
scene problem: report them as missing. Empty, well-lit packing areas are clear. A closed \
bag hiding the order is obscured, not empty. Do not infer "mixed_orders" from the number \
of items, duplicate containers, different food types, spacing, or mat boundaries. A \
large collection can be one order; order membership cannot be determined from appearance alone.
- Ignore non-food background such as the mat, stains, floor, cables and straps. Food \
and drink outside the mat must still be counted or reported as unknown.
- Report every listed menu item exactly once, using its id.
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
- "unknown_items": food or drink objects that match none of the listed menu items. \
Report each with "name" (short description), "count" (positive integer or null) and \
"label_text" (exact readable text, otherwise null). Never force a match. Ignore \
tickets, hands, and shadows.
{box_rule}- Do not decide whether the order is correct. Only report what you see.

Menu items:
{items}
"""


# Boxes cost output tokens (about 30 per object) and so add latency. The design keeps
# them out of the first call; the kitchen asks for them only in dev mode.
BOX_RULE = """\
- For each listed or unknown item, return "boxes": one tight box per visible object \
located ONLY in the LAST image (the order photo), never in reference photos. Each box has \
x_min, y_min, x_max, y_max: integer coordinates normalized to 0–1000, origin top-left, \
x increasing rightward and y downward. Use an empty array for missing/hidden objects \
or when you cannot locate them. Do not invent boxes. Return at most 32 boxes in total; \
counts must still describe all visible objects, even when the box limit is reached.
"""


class VisionCallRejected(RuntimeError):
    """The spending guard refused a call; nothing was sent."""


class VisionProviderError(RuntimeError):
    """Perceptron failed or returned an answer that doesn't fit the request."""


class CallLimiter:
    """Cooldown between call starts and an optional hard cap (``max_calls=None`` for none)."""

    def __init__(self, max_calls: int | None, cooldown_s: float, clock=time.monotonic):
        self.max_calls = max_calls
        self.cooldown_s = cooldown_s
        self.calls = 0
        self._last: float | None = None
        self._clock = clock
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            if self.max_calls is not None and self.calls >= self.max_calls:
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


def build_messages(request: VisionInput, boxes: bool = False) -> list[dict]:
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
    # Ordered and lookalike items are listed alike, in id order, so the prompt never
    # tells the model which one the ticket expects.
    lines = {t.target_id: _target_line(t) for t in request.targets}
    ordered = {t.item_id for t in request.targets}
    for ref in request.references:
        if ref.item_id not in ordered and ref.item_id not in lines:
            line = f"- {ref.item_id}: {ref.name or ref.item_id}"
            if ref.verification_mode == "label":
                line += f' (LABEL REQUIRED: only count it if marked "{ref.name or ref.item_id}")'
            lines[ref.item_id] = line
    content.append(
        {
            "type": "text",
            "text": PROMPT.format(
                box_rule=BOX_RULE if boxes else "",
                items="\n".join(lines[key] for key in sorted(lines)),
            ),
        }
    )
    return [{"role": "user", "content": content}]


def response_schema(
    target_ids: list[str], alternative_ids: list[str] | None = None, boxes: bool = False
) -> dict:
    box_list = {
        "type": "array",
        "maxItems": 32,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["x_min", "y_min", "x_max", "y_max"],
            "properties": {
                key: {"type": "integer", "minimum": 0, "maximum": 1000}
                for key in ("x_min", "y_min", "x_max", "y_max")
            },
        },
    }
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_id",
            "status",
            "count",
            "label_text",
            "unlabeled_count",
            "reason",
            *(["boxes"] if boxes else []),
        ],
        "properties": {
            "item_id": {"type": "string", "enum": sorted([*target_ids, *(alternative_ids or [])])},
            "status": {"type": "string", "enum": list(STATUSES)},
            "count": {"type": ["integer", "null"], "minimum": 0, "maximum": 100000},
            "reason": {"type": "string", "enum": ["none", *REASONS]},
            "label_text": {"type": ["string", "null"]},
            "unlabeled_count": {"type": "integer", "minimum": 0},
            **({"boxes": box_list} if boxes else {}),
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
                "required": ["items", "unknown_items", "scene_status"],
                "properties": {
                    "items": {"type": "array", "items": item},
                    "unknown_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "name",
                                "count",
                                "label_text",
                                *(["boxes"] if boxes else []),
                            ],
                            "properties": {
                                "name": {"type": "string"},
                                "count": {
                                    "type": ["integer", "null"],
                                    "minimum": 1,
                                    "maximum": 100000,
                                },
                                "label_text": {"type": ["string", "null"]},
                                **({"boxes": box_list} if boxes else {}),
                            },
                        },
                    },
                    "scene_status": {"type": "string", "enum": list(SCENES)},
                },
            },
        },
    }


def valid_boxes(value):
    """Bad optional geometry must not invalidate otherwise usable recognition."""
    if not isinstance(value, list):
        return []
    boxes = []
    for entry in value[:32]:
        try:
            boxes.append(BoundingBox.model_validate(entry))
        except (ValueError, TypeError):
            continue
    return boxes


def parse_answer(
    text: str, request: VisionInput
) -> tuple[list[TargetObservation], list[UnexpectedItem]]:
    """Validate the model's JSON against the requested targets. Raises VisionProviderError."""
    try:
        data = json.loads(text)
        entries = data["items"]
        # "unexpected_items" is the pre-inventory answer shape, kept for offline fixtures.
        unexpected = data["unknown_items"] if "unknown_items" in data else data["unexpected_items"]
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
    alternatives = {
        ref.item_id: ref
        for ref in request.references
        if ref.item_id not in {target.item_id for target in request.targets}
    }
    seen: dict[str, TargetObservation] = {}
    listed: list[UnexpectedItem] = []
    reported: set[str] = set()
    for entry in entries:
        target_id = entry.get("item_id")
        if not isinstance(target_id, str) or target_id not in {*targets, *alternatives}:
            raise VisionProviderError(f"unknown item_id {target_id!r}")
        status, count = entry.get("status"), entry.get("count")
        if status not in STATUSES:
            raise VisionProviderError(f"bad status {status!r} for {target_id}")
        if count is not None and (type(count) is not int or not 0 <= count <= 100000):
            raise VisionProviderError(f"bad count {count!r} for {target_id}")
        # Answers that contradict themselves are doubts about this item, not a failed
        # check: the worker sees amber with a reason instead of "Check failed".
        conflict = target_id in reported or (status == "present" and count == 0)
        reported.add(target_id)
        if status == "missing" and count is None:
            count = 0
        elif status == "missing" and count:
            conflict = True
        if conflict:
            if target_id in seen:
                seen[target_id] = seen[target_id].model_copy(
                    update={"status": "unsure", "reason": REASONS["count"]}
                )
                continue
            status, count = "unsure", count or None
            entry = {**entry, "reason": "count"}
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
        if target_id in alternatives:
            # A lookalike that isn't on the ticket. Confidently seen: a wrong item (red).
            # Possibly there: unidentified (amber). LABEL REQUIRED needs its label.
            reference = alternatives[target_id]
            name = reference.name or target_id
            # Only an object actually counted on the mat matters. "Unsure, no count" about
            # a lookalike says nothing about this order, so it isn't shown to the worker.
            if status == "missing" or not count:
                continue
            label_ok = bool(label) and bool(
                re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", label, re.I)
            )
            sure = status == "present" and reason is None and count is not None
            if reference.verification_mode == "label" and not label_ok:
                sure = False
            listed.append(
                UnexpectedItem(
                    name=name,
                    item_id=target_id if sure else None,
                    quantity=count,
                    boxes=valid_boxes(entry.get("boxes")),
                )
            )
            continue
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
        # A poor whole-scene view is reported once as scene_uncertainty and turns the
        # result amber in compare_order; it doesn't rewrite the item counts.
        seen[target_id] = TargetObservation(
            target_id=target_id,
            status=status,
            observed_quantity=count,
            reason=reason,
            label_text=label,
            boxes=[] if status == "missing" else valid_boxes(entry.get("boxes")),
        )
    # An ordered item the model never mentioned wasn't confidently counted either way.
    for target_id in sorted(set(targets) - set(seen)):
        seen[target_id] = TargetObservation(
            target_id=target_id,
            status="unsure",
            observed_quantity=None,
            reason=REASONS["unknown"],
        )
    extras = listed
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
                boxes=valid_boxes(item.get("boxes")),
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
        boxes: bool = False,
        reasoning: str = "none",
    ):
        """``client`` is for tests; otherwise a Perceptron ``AsyncClient`` is built from the key.

        ``reasoning`` is Perceptron's reasoning effort ("none", "low" or "high"). Thinking
        is slower and spends output tokens, so callers raise ``max_output_tokens`` with it.
        """
        self.model = model or os.getenv("PERCEPTRON_MODEL") or DEFAULT_MODEL
        self.max_output_tokens = max_output_tokens
        self.boxes = boxes
        self.reasoning = reasoning
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
        messages = build_messages(request, self.boxes)
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
                    self.boxes,
                ),
                max_completion_tokens=self.max_output_tokens,
                temperature=0,
                reasoning_effort=self.reasoning,
            )
        except Exception as exc:  # SDK errors carry no secrets; keep the type for logs
            raise VisionProviderError(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = round((time.perf_counter() - start) * 1000)
        if completion.finish_reason != "stop":
            error = VisionProviderError(
                f"incomplete answer: finish_reason={completion.finish_reason}"
            )
            error.raw_answer = (completion.text or "")[:4000]
            error.public_reason = str(error)
            raise error
        try:
            observations, unexpected = parse_answer(completion.text or "", request)
            answer = json.loads(completion.text)
            if "scene_status" not in answer:
                raise VisionProviderError("answer left out scene status")
        except VisionProviderError as exc:
            # The kitchen's CV log shows what the model said and why it was rejected.
            exc.raw_answer = (completion.text or "")[:4000]
            exc.public_reason = str(exc)[:300]
            raise
        usage = completion.usage
        return Observations(
            capture_id=request.capture_id,
            targets=observations,
            unexpected_items=unexpected,
            scene_uncertainty=SCENES[answer["scene_status"]],
            provider=ProviderMetadata(
                provider="perceptron",
                model=self.model,
                prompt_version=PROMPT_VERSION
                + ("-boxes" if self.boxes else "")
                + ("" if self.reasoning == "none" else f"-reasoning-{self.reasoning}"),
                latency_ms=latency_ms,
                request_id=getattr(completion, "request_id", None),
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            ),
        )
