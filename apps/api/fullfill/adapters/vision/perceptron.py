"""Perceptron Mk1.5 adapter: one call per check, a strict JSON schema answer.

The order photo goes last, after one labeled reference photo set per target. Expected
quantities are never sent, so the model counts what it sees instead of agreeing with
the ticket. Verdicts are not decided here; see ``fullfill.domain.compare_order``.
"""

import asyncio
import base64
import json
import os
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

DEFAULT_MODEL = "perceptron-mk1.5"
PROMPT_VERSION = "order-check-v2"
STATUSES = ("present", "missing", "unsure")

PROMPT = """\
You check takeout orders at a restaurant packing station. A camera looks down at the \
packing area. The last image is the order photo. Any earlier images are labeled reference \
photos of this restaurant's own menu items, taken with the same camera.

For each item in the list below, count how many of it are clearly visible in the order \
photo. Use the reference photos to tell similar-looking items apart (size, lid or can \
color, flavor printed on the top, packaging shape, printed or handwritten labels).

Rules:
- Report every listed item exactly once, using its id.
- status "present": you can see it; "count" is how many.
- status "missing": you are confident none are there; "count" is 0.
- status "unsure": it may be hidden, cut off, blurry, or you cannot tell it apart from a \
similar item; "count" is your best guess or null.
- Never count one object for two different items.
- "label_text": the exact handwritten or printed text on that item's label, lid or \
wrapper, if readable; otherwise null.
- "unlabeled_count": for items marked LABEL REQUIRED, how many objects look like this \
item but have no readable label, so you can't tell which item they are. Do not include \
those in "count". For other items, 0.
- "unexpected_items": short names of food or drink items in the photo that match none of \
the listed items. Ignore paper tickets, the mat, hands, and shadows.
- Do not decide whether the order is correct. Only report what you see.

Items to check:
{items}
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
        marks = " or ".join(f'"{alias}"' for alias in target.label_aliases)
        line += (
            f" (LABEL REQUIRED: only count it if marked {marks})" if marks else " (LABEL REQUIRED)"
        )
    return line


def build_messages(request: VisionInput) -> list[dict]:
    names = {t.item_id: t.name for t in request.targets}
    content: list[dict] = []
    for ref in request.references:
        label = f"Reference photo of {ref.item_id} ({names.get(ref.item_id, ref.item_id)}):"
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
    content.append({"type": "text", "text": PROMPT.format(items=items)})
    return [{"role": "user", "content": content}]


def response_schema(target_ids: list[str]) -> dict:
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["item_id", "status", "count", "label_text", "unlabeled_count"],
        "properties": {
            "item_id": {"type": "string", "enum": target_ids},
            "status": {"type": "string", "enum": list(STATUSES)},
            "count": {"type": ["integer", "null"], "minimum": 0},
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
                "required": ["items", "unexpected_items"],
                "properties": {
                    "items": {"type": "array", "items": item},
                    "unexpected_items": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


def parse_answer(text: str, request: VisionInput) -> tuple[list[TargetObservation], list[str]]:
    """Validate the model's JSON against the requested targets. Raises VisionProviderError."""
    try:
        data = json.loads(text)
        entries = data["items"]
        unexpected = [str(name) for name in data.get("unexpected_items") or []]
    except (ValueError, KeyError, TypeError) as exc:
        raise VisionProviderError(f"answer is not the requested JSON: {exc}") from exc
    targets = {t.target_id: t for t in request.targets}
    seen: dict[str, TargetObservation] = {}
    for entry in entries:
        target_id = entry.get("item_id")
        if target_id not in targets:
            raise VisionProviderError(f"unknown item_id {target_id!r}")
        if target_id in seen:
            raise VisionProviderError(f"duplicate item_id {target_id!r}")
        status, count = entry.get("status"), entry.get("count")
        if status not in STATUSES:
            raise VisionProviderError(f"bad status {status!r} for {target_id}")
        if count is not None and (not isinstance(count, int) or count < 0):
            raise VisionProviderError(f"bad count {count!r} for {target_id}")
        if status == "missing":
            count = 0
        reason = None
        unlabeled = entry.get("unlabeled_count") or 0
        if targets[target_id].verification_mode == "label" and unlabeled > 0:
            # An unlabeled lookalike might be this item: let the worker decide.
            status = "unsure"
            reason = f"{unlabeled} unlabeled item(s) look like {targets[target_id].name}"
        elif status == "unsure":
            reason = "not clearly visible or hard to tell apart"
        seen[target_id] = TargetObservation(
            target_id=target_id,
            status=status,
            observed_quantity=count,
            reason=reason,
            label_text=entry.get("label_text"),
        )
    missing = sorted(set(targets) - set(seen))
    if missing:
        raise VisionProviderError(f"answer left out {missing}")
    return [seen[t.target_id] for t in request.targets], unexpected


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
        self.limiter = limiter or CallLimiter(max_calls=500, cooldown_s=2.0)
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
        await self.limiter.acquire()
        start = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=response_schema(target_ids),
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
        usage = completion.usage
        return Observations(
            capture_id=request.capture_id,
            targets=observations,
            unexpected_items=[UnexpectedItem(name=name) for name in unexpected],
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
