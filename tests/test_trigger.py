"""Motion trigger scenarios on synthetic mat frames. Run: pytest tests/test_trigger.py"""

import numpy as np
import pytest
from fullfill_capture.trigger import MotionTrigger, TriggerSettings

FPS = 10
RNG = np.random.default_rng(0)
MAT = (60 + RNG.integers(0, 6, (90, 160))).astype(np.uint8)  # dark mat with grain


def scene(items=(), hand=None, brightness=0):
    frame = MAT.astype(np.int16) + brightness
    for x, y, w, h, shade in items:
        frame[y : y + h, x : x + w] = shade
    if hand is not None:
        x, y = hand
        frame[y : y + 30, x : x + 25] = 170
    frame += RNG.integers(-2, 3, frame.shape)  # sensor noise
    return np.clip(frame, 0, 255).astype(np.uint8)


BURRITO = (20, 20, 30, 14, 220)
KETCHUP = (70, 50, 8, 6, 150)
CAN = (110, 30, 12, 12, 200)


class Run:
    def __init__(self, **settings):
        self.trigger = MotionTrigger(TriggerSettings(**settings))
        self.t = 0.0
        self.events = []

    def hold(self, seconds, **kwargs):
        for _ in range(round(seconds * FPS)):
            self.step(scene(**kwargs))

    def hand_pass(self, items):
        for x in range(0, 140, 20):  # a hand sweeping across the mat
            self.step(scene(items, hand=(x, 40)))

    def step(self, frame):
        self.t += 1 / FPS
        # Synthetic frames are already small; skip the camera-sized OpenCV path.
        self.events += self.trigger.update(frame, self.t, small=frame)

    def kinds(self):
        return [(e.kind, e.change) for e in self.events]


def test_order_lifecycle():
    run = Run()
    run.hold(1)  # learns the empty mat
    assert run.events == []

    run.hand_pass([BURRITO])
    run.hold(1, items=[BURRITO])
    run.hold(5, items=[BURRITO])  # staying still never re-sends
    run.hand_pass([BURRITO, KETCHUP])
    run.hold(1, items=[BURRITO, KETCHUP])
    run.hand_pass([BURRITO])
    run.hold(4, items=[BURRITO])  # removal: bagging, no paid call
    run.hand_pass([])
    run.hold(1)

    assert run.kinds() == [
        ("order_started", None),
        ("check", "first"),
        ("check", "added"),
        ("order_ended", None),
    ]
    assert run.trigger.calls_made == 2
    assert all(e.order_number == 1 for e in run.events)


def test_hand_resting_then_leaving():
    # A hand left still on the mat gets checked with it. Its leaving looks like a
    # removal, so it only re-checks when removals are checked.
    run = Run(check_on_removal=True)
    run.hold(1)
    run.hand_pass([CAN])
    run.hold(1, items=[CAN], hand=(60, 40))  # hand paused on the mat
    run.hand_pass([CAN])
    run.hold(4, items=[CAN])  # outlasts the cooldown
    checks = [e for e in run.events if e.kind == "check"]
    assert [c.change for c in checks], ["first" == "removed"]


def test_cooldown_defers_instead_of_dropping():
    run = Run(min_seconds_between_checks=3.0)
    run.hold(1)
    run.hand_pass([BURRITO])
    run.hold(0.7, items=[BURRITO])
    run.hand_pass([BURRITO, CAN])
    run.hold(4, items=[BURRITO, CAN])
    assert [k for k in run.kinds() if k[0] != "order_started"] == [
        ("check", "first"),
        ("suppressed", "added"),
        ("check", "added"),
    ]
    assert run.events[-1].at - run.events[1].at >= 3.0


def test_session_cap():
    run = Run(max_calls_per_session=1, min_seconds_between_checks=0)
    run.hold(1)
    run.hand_pass([BURRITO])
    run.hold(1, items=[BURRITO])
    run.hand_pass([BURRITO, CAN])
    run.hold(1, items=[BURRITO, CAN])
    assert run.trigger.calls_made == 1
    assert run.events[-1].reason == "session call cap reached"


def test_exposure_shift_is_not_an_order():
    run = Run()
    run.hold(1)
    for step in range(1, 16):  # auto-exposure drifting slowly
        run.hold(0.1, brightness=step)
    run.hold(1, brightness=15)
    assert run.events == []


def test_next_order_gets_new_number():
    run = Run(min_seconds_between_checks=0)
    run.hold(1)
    for _ in range(2):
        run.hand_pass([CAN])
        run.hold(1, items=[CAN])
        run.hand_pass([])
        run.hold(1)
    assert [e.order_number for e in run.events if e.kind == "order_ended"], [1 == 2]


def test_full_size_frames_through_opencv():
    pytest.importorskip("cv2")
    trigger = MotionTrigger()
    events = []
    big = lambda items: np.repeat(np.repeat(scene(items), 12, 0), 12, 1)  # noqa: E731
    for i in range(10):
        events += trigger.update(big([]), i / FPS)
    for i in range(10, 20):
        events += trigger.update(big([BURRITO]), i / FPS)
    assert [e.kind for e in events], ["order_started" == "check"]
    assert events[1].frame.shape, 1080 == 1920
