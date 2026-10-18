"""Eval glue for the T1-T3 go/no-go tests.

The request, prompt and answer parsing live in the app's Perceptron adapter
(apps/api/fullfill/adapters/vision/perceptron.py), and verdicts come from
fullfill.domain.compare_order, and reference candidates use the same local selector as the website.
This file adds what only the eval needs: photos from disk, a persistent call
budget, and plain dict results for scoring.
"""
import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
from fullfill.adapters.vision import perceptron as adapter
from fullfill.domain.compare_order import compare_order
from fullfill.domain.reference_selection import choose_alternatives
from fullfill.application.order_source import MenuEntry, MenuSnapshot
from fullfill_contracts.orders import OrderLine, OrderSnapshot
from fullfill_contracts.vision import (
    ImageInput,
    Observations,
    ReferenceImage,
    TargetObservation,
    UnexpectedItem,
    VerificationTarget,
    VisionInput,
)

import config

PROMPT_VERSION = adapter.PROMPT_VERSION
BUDGET_FILE = config.LOG_DIR / "eval" / "call_budget.json"

# Mk1.5 list prices, dollars per million tokens.
INPUT_PRICE = 0.15
OUTPUT_PRICE = 1.50

# Lifetime cap across every eval run, so repeated runs can't add up either.
MAX_TOTAL_CALLS = int(os.getenv("EVAL_MAX_TOTAL_CALLS", "200"))
REFERENCE_MAX_SIDE = 640   # references can be smaller than the order photo


class BudgetExceeded(RuntimeError):
    pass


class CallGuard:
    """Cooldown between calls, a per-run cap, and a lifetime cap saved to disk."""

    def __init__(self, max_calls, cooldown=None, budget_file=BUDGET_FILE,
                 max_total=MAX_TOTAL_CALLS, clock=time.monotonic, sleep=time.sleep):
        self.max_calls = max_calls
        self.cooldown = cooldown if cooldown is not None else 60.0 / config.MAX_CALLS_PER_MINUTE
        self.budget_file = Path(budget_file)
        self.max_total = max_total
        self.calls = 0
        self._last = None
        self._clock = clock
        self._sleep = sleep

    def total_used(self):
        try:
            return json.loads(self.budget_file.read_text())["calls"]
        except (FileNotFoundError, ValueError, KeyError):
            return 0

    def acquire(self):
        """Wait out the cooldown and count the call. Raises before going over a cap."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"run cap of {self.max_calls} calls reached")
        total = self.total_used()
        if total >= self.max_total:
            raise BudgetExceeded(
                f"lifetime cap of {self.max_total} eval calls reached ({self.budget_file}); "
                "raise EVAL_MAX_TOTAL_CALLS if this is intended")
        if self._last is not None:
            wait = self.cooldown - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        # Count before calling: a call that fails still may have cost credits.
        self.budget_file.parent.mkdir(parents=True, exist_ok=True)
        self.budget_file.write_text(json.dumps({"calls": total + 1}))
        self.calls += 1
        self._last = self._clock()


def encode_image(path, max_side):
    """Downscale to max_side and return a JPEG data URL."""
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes(path, max_side)).decode()


def jpeg_bytes(path, max_side):
    """Downscale to max_side and return JPEG bytes."""
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"can't read image {path}")
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY])
    if not ok:
        raise ValueError(f"can't encode image {path}")
    return buf.tobytes()


def reference_photos(item_id, limit):
    folder = config.REFERENCE_DIR / item_id
    photos = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    return photos[:limit]


def make_target(item_id, menu):
    """Menu entries may set "label": ["C"] to require a readable label for that item."""
    item = menu[item_id]
    labels = item.get("label") or []
    name = item["name"] + (f" ({item['description']})" if item.get("description") else "")
    # expected_quantity is required by the contract but never sent to the model.
    return VerificationTarget(target_id=item_id, line_ids=[item_id], item_id=item_id, name=name,
                              expected_quantity=1, verification_mode="label" if labels else "visible_item",
                              label_aliases=list(labels))


def build_request(image_path, item_ids, menu, use_references, refs_per_item):
    refs = []
    if use_references:
        saved = {i: [ImageInput(jpeg_bytes(path, REFERENCE_MAX_SIDE), "image/jpeg")
                     for path in reference_photos(i, refs_per_item)] for i in menu}
        snapshot = MenuSnapshot(revision="eval", items=[MenuEntry(
            item_id=i, name=details["name"], description="", price_cents=0,
            verification_mode="label" if details.get("label") else "visible_item")
            for i, details in menu.items()])
        first_images = {i: photos[0] for i, photos in saved.items() if photos}
        missing = set(item_ids) - first_images.keys()
        if missing:
            raise FileNotFoundError("Missing reference photos: " + ", ".join(sorted(missing)))
        alternatives = choose_alternatives(snapshot, set(item_ids), first_images)
        included = list(item_ids) + [item.item_id for item in alternatives]
        for item_id in included:
            for image in saved[item_id]:
                refs.append(ReferenceImage(item_id=item_id, revision=1, image=image,
                                           name=menu[item_id]["name"],
                                           verification_mode="label" if menu[item_id].get("label") else "visible_item"))
    image = ImageInput(jpeg_bytes(image_path, config.UPLOAD_MAX_SIDE), "image/jpeg")
    return VisionInput(capture_id=str(image_path), image=image,
                       targets=tuple(make_target(i, menu) for i in item_ids), references=tuple(refs))


def build_messages(image_path, item_ids, menu, use_references, refs_per_item):
    request = build_request(image_path, item_ids, menu, use_references, refs_per_item)
    return adapter.build_messages(request), len(request.references)


@dataclass
class CheckResult:
    ok: bool
    latency_s: float
    items: dict = field(default_factory=dict)        # item_id -> {"status", "count", "label_text", "reason"}
    unexpected: list = field(default_factory=list)
    error: str | None = None
    raw: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    n_references: int = 0
    scene_uncertainty: str | None = None

    @property
    def cost(self):
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return (self.prompt_tokens * INPUT_PRICE + self.completion_tokens * OUTPUT_PRICE) / 1e6


def to_items(observations):
    return {o.target_id: {"status": o.status, "count": o.observed_quantity, "label_text": o.label_text,
                          "reason": o.reason} for o in observations.targets}


def parse_answer(text, item_ids, menu=None):
    """The adapter's answer validation, returning plain dicts. Raises ValueError."""
    menu = menu or {i: {"name": i} for i in item_ids}
    request = VisionInput(capture_id="parse", image=ImageInput(b"", "image/jpeg"),
                          targets=tuple(make_target(i, menu) for i in item_ids), references=())
    try:
        targets, unexpected = adapter.parse_answer(text, request)
    except adapter.VisionProviderError as exc:
        raise ValueError(str(exc)) from exc
    return to_items(Observations(capture_id="parse", targets=targets)), [item.model_dump(exclude_none=True) for item in unexpected]


def make_client(model=None):
    if not config.PERCEPTRON_API_KEY:
        raise SystemExit("Set PERCEPTRON_API_KEY in your environment or the untracked .env file.")
    # The eval's CallGuard does the cooldown and caps; the adapter's own limiter just mustn't interfere.
    return adapter.PerceptronVision(
        config.PERCEPTRON_API_KEY, model=model or config.PERCEPTRON_MODEL or None,
        max_output_tokens=config.MAX_OUTPUT_TOKENS, timeout_s=config.REQUEST_TIMEOUT_SECONDS,
        limiter=adapter.CallLimiter(max_calls=10_000, cooldown_s=0))


def check_order(vision, guard, image_path, item_ids, menu, use_references=True, refs_per_item=1, model=None):
    """Run one check through the app's adapter. API and parse failures come back as ok=False."""
    request = build_request(image_path, item_ids, menu, use_references, refs_per_item)
    n_refs = len(request.references)
    if model:
        vision.model = model
    guard.acquire()
    start = time.perf_counter()
    try:
        observations = asyncio.run(vision.inspect(request))
    except adapter.VisionProviderError as exc:
        return CheckResult(ok=False, latency_s=time.perf_counter() - start, n_references=n_refs, error=str(exc))
    latency = time.perf_counter() - start
    provider = observations.provider
    return CheckResult(ok=True, latency_s=latency, items=to_items(observations),
                       unexpected=[u.model_dump(exclude_none=True) for u in observations.unexpected_items],
                       scene_uncertainty=observations.scene_uncertainty,
                       raw=observations.model_dump_json(), n_references=n_refs,
                       prompt_tokens=provider.prompt_tokens if provider else None,
                       completion_tokens=provider.completion_tokens if provider else None)


COLORS = {"pass": "green", "fail": "red", "unsure": "amber"}


def verdict(order, result):
    """green / red / amber from the app's own decision rules; "error" if the call failed.

    order is {item_id: quantity}.
    """
    if not result.ok:
        return "error"
    snapshot = OrderSnapshot(order_id="eval", revision=1, lines=[
        OrderLine(line_id=i, item_id=i, name=i, quantity=q) for i, q in order.items()])
    observations = Observations(capture_id="eval", targets=[
        TargetObservation(target_id=i, status=seen["status"], observed_quantity=seen["count"],
                          reason=seen.get("reason"), label_text=seen.get("label_text"))
        for i, seen in result.items.items() if i in order])
    observations.scene_uncertainty = result.scene_uncertainty
    if result.unexpected:
        observations.unexpected_items.extend(UnexpectedItem(name=n) if isinstance(n, str) else UnexpectedItem(**n)
                                            for n in result.unexpected)
    return COLORS[compare_order(snapshot, observations).verdict]
