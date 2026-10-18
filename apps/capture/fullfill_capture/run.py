"""Run the motion trigger on the phone camera or a recorded clip.

    uv run --no-sync python -m fullfill_capture.run --source 0 --preview
    uv run --no-sync python -m fullfill_capture.run --source clip.mov --preview

Start with the mat clear: the first still scene becomes the empty-mat baseline.
Preview keys: q quit, e re-learn empty mat, c manual check, r drag a new mat crop.

Checks go to a fake vision call that only saves the JPEG and logs a line, so this
spends no Perceptron credits. Swap `fake_vision` for the real adapter when it lands.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from fullfill_contracts.vision import ImageInput

from .prepare_image import prepare_upload
from .trigger import MotionTrigger, TriggerEvent, TriggerSettings

COLORS = {"moving": (0, 0, 255), "settling": (0, 191, 255), "settled": (0, 200, 0)}


def fake_vision(image: ImageInput, path: Path) -> dict:
    path.write_bytes(image.data)
    time.sleep(1.0)  # roughly a real call's latency
    return {"fake": True, "snapshot": path.name, "bytes": len(image.data)}


def log(kind: str, **fields) -> None:
    print(json.dumps({"t": time.strftime("%H:%M:%S"), "event": kind, **fields}), flush=True)


def parse_roi(text: str | None):
    if not text:
        return None
    x, y, w, h = (int(part) for part in text.split(","))
    return (x, y, w, h)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default="0", help="camera index or video file")
    parser.add_argument("--roi", help="mat crop as x,y,w,h in full-frame pixels")
    parser.add_argument("--preview", action="store_true", help="show a window with state")
    parser.add_argument("--out", default="logs/snapshots", help="where fake checks save JPEGs")
    parser.add_argument("--still", type=float, default=0.5, help="seconds of stillness")
    parser.add_argument("--cooldown", type=float, default=1.0, help="seconds between calls")
    parser.add_argument("--max-calls", type=int, default=500, help="hard cap for this run")
    parser.add_argument("--check-removals", action="store_true", help="also check removals")
    args = parser.parse_args()

    import cv2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = TriggerSettings(
        mat_roi=parse_roi(args.roi),
        still_seconds=args.still,
        min_seconds_between_checks=args.cooldown,
        max_calls_per_session=args.max_calls,
        check_on_removal=args.check_removals,
    )
    trigger = MotionTrigger(settings)
    source = int(args.source) if args.source.isdigit() else args.source
    camera = cv2.VideoCapture(source)
    if not camera.isOpened():
        raise SystemExit(f"could not open camera/video {args.source!r}")
    is_file = not isinstance(source, int)
    fps = camera.get(cv2.CAP_PROP_FPS) or 30
    vision = ThreadPoolExecutor(max_workers=1)  # at most one call in flight
    started = time.monotonic()
    frame_index = 0

    def submit(event: TriggerEvent) -> None:
        image = prepare_upload(event.frame, settings.mat_roi)
        log("check", order=event.order_number, change=event.change, calls=trigger.calls_made)
        name = f"call{trigger.calls_made:03d}_order{event.order_number:03d}_{event.change}.jpg"
        future = vision.submit(fake_vision, image, out_dir / name)
        future.add_done_callback(
            lambda done, n=event.order_number: log("result", order=n, **done.result())
        )

    log("start", source=args.source, note="keep the mat clear until the first 'settled'")
    while True:
        ok, frame = camera.read()
        if not ok:
            break
        frame_index += 1
        # Replay files at their own clock so stillness timing matches the recording.
        now = started + frame_index / fps if is_file else time.monotonic()
        had_baseline = trigger.empty is not None
        for event in trigger.update(frame, now):
            if event.kind == "check":
                submit(event)
            else:
                log(event.kind, order=event.order_number, change=event.change, why=event.reason)
        if not had_baseline and trigger.empty is not None:
            log("empty_mat_learned")

        if args.preview:
            view = frame.copy()
            if settings.mat_roi:
                x, y, w, h = settings.mat_roi
                cv2.rectangle(view, (x, y), (x + w, y + h), (255, 255, 255), 2)
            order = f"order {trigger.order_number}" if trigger.order_active else "no order"
            label = f"{trigger.state}  motion {trigger.motion:.3f}  {order}"
            label += f"  calls {trigger.calls_made}"
            cv2.putText(view, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        COLORS[trigger.state], 2)  # fmt: skip
            cv2.imshow("FullFill trigger", view)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("e"):
                trigger.calibrate_empty()
                log("relearning_empty_mat")
            if key == ord("c"):
                for event in trigger.request_check(frame, now):
                    submit(event) if event.kind == "check" else log(event.kind, why=event.reason)
            if key == ord("r"):
                x, y, w, h = cv2.selectROI("FullFill trigger", frame, showCrosshair=False)
                if w and h:
                    settings = replace(settings, mat_roi=(x, y, w, h))
                    budget, trigger = trigger.budget, MotionTrigger(settings)
                    trigger.budget = budget  # a new crop must not reset the spending caps
                    log("roi", roi=f"{x},{y},{w},{h}", note="pass this as --roi next time")

    camera.release()
    vision.shutdown(wait=True)
    if args.preview:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
