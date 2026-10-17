"""Perceptron request layer for the T1-T3 go/no-go tests.

One call per check: the order photo, plus reference photos for only the items
on that ticket, with a JSON schema answer. A cooldown and a hard call cap stop
a bug from burning the credits. Kept small so Roy's backend adapter can copy it.
"""
import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

import config

PROMPT_FILE = Path(__file__).with_name("prompt_v1.txt")
PROMPT_VERSION = PROMPT_FILE.stem
BUDGET_FILE = config.LOG_DIR / "eval" / "call_budget.json"

# Mk1.5 list prices, dollars per million tokens.
INPUT_PRICE = 0.15
OUTPUT_PRICE = 1.50

# Lifetime cap across every eval run, so repeated runs can't add up either.
MAX_TOTAL_CALLS = int(os.getenv("EVAL_MAX_TOTAL_CALLS", "200"))
REFERENCE_MAX_SIDE = 512   # references can be smaller than the order photo


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
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def reference_photos(item_id, limit):
    folder = config.REFERENCE_DIR / item_id
    photos = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    return photos[:limit]


def response_schema(item_ids):
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
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["item_id", "status", "count", "label_text"],
                            "properties": {
                                "item_id": {"type": "string", "enum": list(item_ids)},
                                "status": {"type": "string", "enum": list(config.ITEM_STATUSES)},
                                "count": {"type": ["integer", "null"], "minimum": 0},
                                "label_text": {"type": ["string", "null"]},
                            },
                        },
                    },
                    "unexpected_items": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


def build_messages(image_path, item_ids, menu, use_references, refs_per_item):
    """The order photo comes last; each reference is labeled with its item id.

    Expected quantities are not sent, so the model counts instead of agreeing.
    """
    content = []
    n_refs = 0
    if use_references:
        for item_id in item_ids:
            for ref in reference_photos(item_id, refs_per_item):
                content.append({"type": "text", "text": f"Reference photo of {item_id} ({menu[item_id]['name']}):"})
                content.append({"type": "image_url", "image_url": {"url": encode_image(ref, REFERENCE_MAX_SIDE)}})
                n_refs += 1
    lines = []
    for item_id in item_ids:
        item = menu[item_id]
        desc = f" - {item['description']}" if item.get("description") else ""
        lines.append(f"- {item_id}: {item['name']}{desc}")
    content.append({"type": "text", "text": "Order photo:"})
    content.append({"type": "image_url", "image_url": {"url": encode_image(image_path, config.UPLOAD_MAX_SIDE)}})
    content.append({"type": "text", "text": PROMPT_FILE.read_text().format(items="\n".join(lines))})
    return [{"role": "user", "content": content}], n_refs


@dataclass
class CheckResult:
    ok: bool
    latency_s: float
    items: dict = field(default_factory=dict)        # item_id -> {"status", "count", "label_text"}
    unexpected: list = field(default_factory=list)
    error: str | None = None
    raw: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    n_references: int = 0

    @property
    def cost(self):
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return (self.prompt_tokens * INPUT_PRICE + self.completion_tokens * OUTPUT_PRICE) / 1e6


def parse_answer(text, item_ids):
    """Validate the model's JSON against the requested items. Raises ValueError."""
    data = json.loads(text)
    items = {}
    for entry in data["items"]:
        item_id = entry["item_id"]
        if item_id not in item_ids:
            raise ValueError(f"unknown item_id {item_id!r}")
        if item_id in items:
            raise ValueError(f"duplicate item_id {item_id!r}")
        if entry["status"] not in config.ITEM_STATUSES:
            raise ValueError(f"bad status {entry['status']!r}")
        count = entry["count"]
        if count is not None and (not isinstance(count, int) or count < 0):
            raise ValueError(f"bad count {count!r} for {item_id}")
        items[item_id] = {"status": entry["status"], "count": count, "label_text": entry.get("label_text")}
    missing = set(item_ids) - set(items)
    if missing:
        raise ValueError(f"answer left out {sorted(missing)}")
    return items, list(data.get("unexpected_items") or [])


def make_client():
    from perceptron import Client

    if not config.PERCEPTRON_API_KEY:
        raise SystemExit("Set PERCEPTRON_API_KEY in your environment or the untracked .env file.")
    return Client(api_key=config.PERCEPTRON_API_KEY, timeout=config.REQUEST_TIMEOUT_SECONDS)


def check_order(client, guard, image_path, item_ids, menu, use_references=True, refs_per_item=1,
                model=None):
    """Run one Perceptron check. Never raises for API or parse failures; those come back as ok=False."""
    messages, n_refs = build_messages(image_path, item_ids, menu, use_references, refs_per_item)
    guard.acquire()
    start = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=model or config.PERCEPTRON_MODEL or "perceptron-mk1.5",
            messages=messages,
            response_format=response_schema(item_ids),
            max_completion_tokens=config.MAX_OUTPUT_TOKENS,
            temperature=0,
            reasoning_effort=None if config.USE_REASONING else "none",
        )
    except Exception as exc:  # the SDK raises SDKError subclasses; record and move on
        return CheckResult(ok=False, latency_s=time.perf_counter() - start, n_references=n_refs,
                           error=f"{type(exc).__name__}: {exc}")
    latency = time.perf_counter() - start
    usage = completion.usage
    result = CheckResult(ok=False, latency_s=latency, raw=completion.text, n_references=n_refs,
                         prompt_tokens=usage.prompt_tokens if usage else None,
                         completion_tokens=usage.completion_tokens if usage else None)
    if completion.finish_reason != "stop":
        result.error = f"finish_reason={completion.finish_reason}"
        return result
    try:
        result.items, result.unexpected = parse_answer(completion.text or "", item_ids)
    except (ValueError, KeyError, TypeError) as exc:
        result.error = f"invalid answer: {exc}"
        return result
    result.ok = True
    return result


def verdict(order, result):
    """green / amber / red for an order {item_id: quantity}, the way the station screen would show it.

    A definite count mismatch is red. Anything unsure, unreadable, or unexpected is amber.
    A failed call is "error": it never counts as a pass.
    """
    if not result.ok:
        return "error"
    red = amber = False
    for item_id, expected in order.items():
        seen = result.items[item_id]
        if seen["status"] == "unsure" or seen["count"] is None:
            amber = True
        elif seen["count"] != expected:
            red = True
    if result.unexpected:
        amber = True
    return "red" if red else "amber" if amber else "green"
