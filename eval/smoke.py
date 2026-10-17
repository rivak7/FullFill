"""Smoke test: does Perceptron see one labeled item? 3 calls, names only, no references.

    python -m eval.smoke path/to/photo.jpg

1. Open question, no hints: what food is on the mat, and what is written on it.
2. The real order-check request for one chicken burrito marked "C".
3. Lookalike check: same wrap marked "C" vs "S"; it should count 1 chicken, 0 steak.
"""
import sys
import time
from pathlib import Path

import config
from eval import vision

MENU = {
    "chicken_burrito": {"name": "Chicken burrito", "description": "red checkered paper wrap, marked C in marker"},
    "steak_burrito": {"name": "Steak burrito", "description": "red checkered paper wrap, marked S in marker"},
}
OPEN_QUESTION = ("List each food item you can see on the brown paper, and read out exactly any handwritten "
                 "letters or words on it. Ignore the chair and the table.")


def show(title, result, want):
    print(f"\n{title}  ({result.latency_s:.2f} s)")
    if not result.ok:
        print(f"  FAILED: {result.error}\n  raw: {result.raw}")
        return False
    for item_id, seen in result.items.items():
        print(f"  {item_id}: {seen['status']}, count {seen['count']}, label {seen['label_text']!r}")
    if result.unexpected:
        print(f"  unexpected: {result.unexpected}")
    good = all(result.items[i]["count"] == n for i, n in want.items())
    print(f"  -> {'OK' if good else 'WRONG'} (wanted {want})")
    return good


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    image = Path(sys.argv[1])
    client = vision.make_client()
    guard = vision.CallGuard(max_calls=3)
    model = config.PERCEPTRON_MODEL or "perceptron-mk1.5"

    guard.acquire()
    start = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": vision.encode_image(image, config.UPLOAD_MAX_SIDE)}},
                {"type": "text", "text": OPEN_QUESTION},
            ]}],
            max_completion_tokens=config.MAX_OUTPUT_TOKENS,
            reasoning_effort="none",
        )
        print(f"1. Open question  ({time.perf_counter() - start:.2f} s)\n  {completion.text}")
    except Exception as exc:
        sys.exit(f"1. Open question FAILED: {type(exc).__name__}: {exc}\nFix this before spending more calls.")

    one = vision.check_order(client, guard, image, ["chicken_burrito"], MENU, use_references=False, model=model)
    ok2 = show("2. Order check: 1 chicken burrito", one, {"chicken_burrito": 1})
    if ok2:
        label = one.items["chicken_burrito"]["label_text"]
        print(f"  label read as {label!r}: {'OK' if (label or '').strip().upper() == 'C' else 'WRONG'}")

    two = vision.check_order(client, guard, image, ["chicken_burrito", "steak_burrito"], MENU,
                             use_references=False, model=model)
    ok3 = show("3. Lookalike: chicken (C) vs steak (S)", two, {"chicken_burrito": 1, "steak_burrito": 0})

    print(f"\nSmoke test {'PASSED' if ok2 and ok3 else 'FAILED'}. "
          f"{guard.total_used()}/{guard.max_total} lifetime eval calls used.")
    return 0 if ok2 and ok3 else 1


if __name__ == "__main__":
    sys.exit(main())
