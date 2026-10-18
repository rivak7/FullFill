"""Live demo without a POS: camera trigger -> Perceptron -> green / red / amber.

    python -m eval.live --fake                        # no calls: every check comes back green
    python -m eval.live                               # real Perceptron calls
    python -m eval.live --order chicken_burrito=1,ketchup=3

The ticket comes from eval/live_order.json (copy live_order.example.json), or --order
overrides its quantities. Reference photos are read from data/references/<item_id>/,
taken with eval.capture; items without any are checked by name only.

Start with the mat clear. Keys: q quit, e re-learn empty mat, c check now, r drag mat crop.
Every check is logged to logs/live/<time>.jsonl and its photo saved next to it.
"""
import argparse
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import cv2
from fullfill.adapters.vision import perceptron as adapter
from fullfill.domain.compare_order import compare_order, targets_for
from fullfill_capture.prepare_image import prepare_upload
from fullfill_capture.trigger import MotionTrigger, TriggerSettings
from fullfill_contracts.orders import MenuItem, OrderLine, OrderSnapshot
from fullfill_contracts.vision import (
    ImageInput,
    Observations,
    ReferenceImage,
    TargetObservation,
    VisionInput,
)

import config
from eval import vision

ORDER_FILE = Path(__file__).with_name("live_order.json")
EXAMPLE_FILE = Path(__file__).with_name("live_order.example.json")
BGR = {"pass": (60, 170, 60), "fail": (50, 50, 210), "unsure": (0, 170, 240),
       "checking": (120, 120, 120), "error": (40, 40, 40), "idle": (90, 90, 90)}
HEADLINE = {"pass": "Order fulfilled", "fail": "Order unfulfilled", "unsure": "Needs a quick look",
            "checking": "Checking...", "error": "Couldn't check: check by hand", "idle": "Lay out the order"}


def load_ticket(override):
    path = ORDER_FILE if ORDER_FILE.exists() else EXAMPLE_FILE
    data = json.loads(path.read_text())
    menu, order = data["menu"], data["order"]
    if override:
        order = {k: int(v) for k, v in (part.split("=") for part in override.split(","))}
    unknown = [i for i in order if i not in menu]
    if unknown:
        raise SystemExit(f"not in the menu of {path.name}: {unknown}")
    return menu, order


def build(menu, order):
    lines = [OrderLine(line_id=i, item_id=i, name=menu[i]["name"], quantity=q) for i, q in order.items()]
    snapshot = OrderSnapshot(order_id="live", revision=1, lines=lines)
    menu_items = {i: MenuItem(item_id=i, name=menu[i]["name"],
                              verification_mode="label" if menu[i].get("label") else "visible_item",
                              label_aliases=menu[i].get("label") or []) for i in order}
    # Descriptions help the model, so the target names carry them, as in the eval.
    targets = tuple(t.model_copy(update={"name": vision.make_target(t.item_id, menu).name})
                    for t in targets_for(snapshot, menu_items))
    refs = tuple(ReferenceImage(item_id=i, revision=1,
                                image=ImageInput(vision.jpeg_bytes(p, vision.REFERENCE_MAX_SIDE), "image/jpeg"))
                 for i in order for p in vision.reference_photos(i, 1))
    return snapshot, menu_items, targets, refs


class FakeVision:
    """Sees exactly the ticket. Tests the plumbing and screen without spending calls."""

    async def inspect(self, request):
        await asyncio.sleep(1.0)
        return Observations(capture_id=request.capture_id, targets=[
            TargetObservation(target_id=t.target_id, status="present", observed_quantity=t.expected_quantity)
            for t in request.targets])


def draw(frame, roi, trigger, menu, order, screen):
    view = frame.copy()
    if roi:
        x, y, w, h = roi
        cv2.rectangle(view, (x, y), (x + w, y + h), (255, 255, 255), 2)
    color = screen["state"]
    cv2.rectangle(view, (0, 0), (view.shape[1], 90), BGR[color], -1)
    cv2.putText(view, HEADLINE[color], (20, 62), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    lines = [f"{q} x {menu[i]['name']}" for i, q in order.items()]
    lines += [""] + screen["messages"]
    lines += ["", f"{trigger.state}  motion {trigger.motion:.3f}  calls {trigger.calls_made}"]
    for n, text in enumerate(lines):
        cv2.putText(view, text, (20, 140 + 36 * n), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 4)
        cv2.putText(view, text, (20, 140 + 36 * n), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
    return view


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fake", action="store_true", help="no Perceptron calls")
    parser.add_argument("--order", help="item_id=qty,... instead of the file's order")
    parser.add_argument("--source", default=str(config.CAMERA_INDEX), help="camera index or video file")
    parser.add_argument("--max-calls", type=int, default=50, help="hard cap for this run")
    parser.add_argument("--check-removals", action="store_true")
    args = parser.parse_args()

    menu, order = load_ticket(args.order)
    snapshot, menu_items, targets, refs = build(menu, order)
    print(f"ticket: {order}; reference photos: {sorted({r.item_id for r in refs}) or 'none'}")
    provider = FakeVision() if args.fake else vision.make_client()

    settings = TriggerSettings(mat_roi=config.MAT_ROI, still_seconds=config.STILL_SECONDS,
                               min_seconds_between_checks=config.MIN_SECONDS_BETWEEN_CHECKS,
                               max_calls_per_minute=config.MAX_CALLS_PER_MINUTE,
                               max_calls_per_session=args.max_calls, check_on_removal=args.check_removals)
    trigger = MotionTrigger(settings)
    log_dir = config.LOG_DIR / "live"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    screen = {"state": "idle", "messages": [], "check": 0}
    worker = ThreadPoolExecutor(max_workers=1)  # one call in flight; newer checks queue behind

    def run_check(number, image):
        start = time.perf_counter()
        request = VisionInput(capture_id=f"live-{number}", image=image, targets=targets, references=refs)
        try:
            observations = asyncio.run(provider.inspect(request))
            result = compare_order(snapshot, observations, menu_items)
            state, messages = result.verdict, [d.message for d in result.discrepancies]
            detail = observations.model_dump(mode="json")
        except (adapter.VisionProviderError, adapter.VisionCallRejected, ValueError) as exc:
            state, messages, detail = "error", [str(exc)[:80]], None
        seconds = round(time.perf_counter() - start, 2)
        if number == screen["check"]:  # an older answer never replaces a newer check
            screen.update(state=state, messages=messages)
        print(f"check {number}: {state.upper()} in {seconds}s {messages}")
        with log_file.open("a") as f:
            f.write(json.dumps({"check": number, "verdict": state, "messages": messages,
                                "seconds": seconds, "observations": detail}) + "\n")

    def submit(event):
        screen["check"] += 1
        number = screen["check"]
        screen.update(state="checking", messages=[])
        image = prepare_upload(event.frame, settings.mat_roi, config.UPLOAD_MAX_SIDE, config.JPEG_QUALITY)
        (log_dir / f"{log_file.stem}_check{number:03d}.jpg").write_bytes(image.data)
        print(f"check {number}: {event.change} -> sending")
        worker.submit(run_check, number, image)

    source = int(args.source) if args.source.isdigit() else args.source
    camera = cv2.VideoCapture(source)
    if isinstance(source, int):
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    if not camera.isOpened():
        raise SystemExit(f"can't open camera {args.source}; try --source 1")
    is_file = not isinstance(source, int)
    fps, frames, started = camera.get(cv2.CAP_PROP_FPS) or 30, 0, time.monotonic()
    print("keep the mat clear for a moment so the empty mat is learned")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                if not is_file:
                    continue
                break
            frames += 1
            # A recorded clip plays at its own clock so stillness timing matches it.
            now = started + frames / fps if is_file else time.monotonic()
            for event in trigger.update(frame, now):
                if event.kind == "check":
                    submit(event)
                elif event.kind == "order_started":
                    print("order started")
                elif event.kind == "order_ended":
                    print("mat clear: order ended")
                    screen.update(state="idle", messages=[])
                else:
                    print(f"skipped a check: {event.reason}")
            cv2.imshow("FullFill live", draw(frame, settings.mat_roi, trigger, menu, order, screen))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("e"):
                trigger.calibrate_empty()
            if key == ord("c"):
                for event in trigger.request_check(frame, now):
                    submit(event) if event.kind == "check" else print(f"skipped: {event.reason}")
            if key == ord("r"):
                x, y, w, h = cv2.selectROI("FullFill live", frame, showCrosshair=False)
                if w and h:
                    settings = replace(settings, mat_roi=(x, y, w, h))
                    budget, trigger = trigger.budget, MotionTrigger(settings)
                    trigger.budget = budget
                    print(f"mat crop {x},{y},{w},{h}: put MAT_ROI = ({x}, {y}, {w}, {h}) in config.py")
    finally:
        camera.release()
        worker.shutdown(wait=True)
        cv2.destroyAllWindows()
        print(f"log: {log_file}")


if __name__ == "__main__":
    main()
