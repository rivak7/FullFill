"""Decide when a camera frame is worth a paid Perceptron call.

The trigger watches small, blurred color copies of the mat. It does nothing while hands
move. Once the mat has been still for `still_seconds` and the scene differs from the
last one it reported, it emits one event:

- ``order_started``: something appeared on an empty mat (followed by a check).
- ``check``: a settled change worth a vision call, e.g. an item added. The event
  carries the full-resolution frame from the settled moment.
- ``order_ended``: the mat is back to its empty baseline.
- ``suppressed``: a check was wanted but a spending guard blocked it.

Removals inside an active order are reported as ``change="removed"``. By default they
don't spend a call, because removal usually means bagging (see system-design.md).

The empty mat is learned from the first settled scene, so start the loop with the mat
clear, or call ``calibrate_empty()`` later. Nothing here opens a camera.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

EventKind = Literal["order_started", "check", "order_ended", "suppressed"]
ChangeKind = Literal["first", "added", "removed", "changed", "manual"]


@dataclass(frozen=True)
class TriggerSettings:
    # Width of the analysis copy; the mat crop is shrunk to this before comparing.
    analysis_width: int = 160
    # A pixel "moved" when any color channel changes by more than this.
    pixel_delta: int = 25
    # The mat is in motion when more than this fraction of its pixels moved.
    motion_fraction: float = 0.004
    still_seconds: float = 0.5
    # A settled scene counts as different when a solid patch of at least this many
    # analysis pixels changed; at 160 px wide a sauce packet covers roughly 50-100.
    min_change_pixels: int = 12
    # Spending guards, matching config.py.
    min_seconds_between_checks: float = 1.0
    max_calls_per_minute: int = 30
    max_calls_per_session: int = 500
    check_on_removal: bool = False
    # A crop (x, y, width, height) of the full frame that covers the mat.
    mat_roi: tuple[int, int, int, int] | None = None


@dataclass
class TriggerEvent:
    kind: EventKind
    at: float
    order_number: int
    frame: Any = None
    change: ChangeKind | None = None
    changed_fraction: float = 0.0
    reason: str | None = None


@dataclass
class _CallBudget:
    settings: TriggerSettings
    recent: deque[float] = field(default_factory=deque)
    total: int = 0

    def blocked_reason(self, now: float) -> str | None:
        while self.recent and now - self.recent[0] >= 60:
            self.recent.popleft()
        if self.total >= self.settings.max_calls_per_session:
            return "session call cap reached"
        if len(self.recent) >= self.settings.max_calls_per_minute:
            return "per-minute call cap reached"
        if self.recent and now - self.recent[-1] < self.settings.min_seconds_between_checks:
            return "cooldown"
        return None

    def spend(self, now: float) -> None:
        self.recent.append(now)
        self.total += 1


def crop_mat(frame: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    if roi is None:
        return frame
    x, y, w, h = roi
    return frame[y : y + h, x : x + w]


def analysis_copy(frame: np.ndarray, settings: TriggerSettings) -> np.ndarray:
    """Small, blurred copy of the mat. Color stays: red ketchup on brown cardboard
    can have the same brightness as the cardboard."""
    import cv2

    mat = crop_mat(frame, settings.mat_roi)
    height = max(1, round(mat.shape[0] * settings.analysis_width / mat.shape[1]))
    small = cv2.resize(mat, (settings.analysis_width, height), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(small, (5, 5), 0)


def _over(diff: np.ndarray, pixel_delta: int) -> np.ndarray:
    diff = np.abs(diff)
    return (diff.max(axis=2) if diff.ndim == 3 else diff) > pixel_delta


def _changed(a: np.ndarray, b: np.ndarray, pixel_delta: int) -> np.ndarray:
    return _over(a.astype(np.int16) - b.astype(np.int16), pixel_delta)


def _scene_diff(a: np.ndarray, b: np.ndarray, pixel_delta: int) -> np.ndarray:
    # Auto-exposure shifts the whole frame; compare scenes with that shift removed.
    diff = a.astype(np.int16) - b.astype(np.int16)
    shift = np.median(diff.reshape(diff.shape[0] * diff.shape[1], -1), axis=0)
    return _over(diff - shift.astype(np.int16), pixel_delta)


def _solid(mask: np.ndarray) -> np.ndarray:
    """Keep changed pixels whose four neighbours changed too, dropping speckle."""
    core = mask.copy()
    core[1:, :] &= mask[:-1, :]
    core[:-1, :] &= mask[1:, :]
    core[:, 1:] &= mask[:, :-1]
    core[:, :-1] &= mask[:, 1:]
    return core


class MotionTrigger:
    """Feed every camera frame to `update`; act on the events it returns."""

    def __init__(self, settings: TriggerSettings | None = None) -> None:
        self.settings = settings or TriggerSettings()
        self.budget = _CallBudget(self.settings)
        self.empty: np.ndarray | None = None
        self.order_number = 0
        self.order_active = False
        self.state: Literal["moving", "settling", "settled"] = "moving"
        self.motion = 0.0
        self._previous: np.ndarray | None = None
        self._still_since: float | None = None
        self._reported: np.ndarray | None = None  # last scene acted on
        self._submitted: np.ndarray | None = None  # last scene sent for a check
        self._pending: TriggerEvent | None = None  # check waiting out a cooldown
        self._calibrate_next = False

    @property
    def calls_made(self) -> int:
        return self.budget.total

    def calibrate_empty(self) -> None:
        """Treat the next settled scene as the empty mat."""
        self._calibrate_next = True

    def request_check(self, frame: Any, now: float | None = None) -> list[TriggerEvent]:
        """Manual Check button: skips the scene logic but not the spending guards."""
        now = time.monotonic() if now is None else now
        if not self.order_active:
            return []
        return self._check(frame, now, "manual", 1.0)

    def update(self, frame: Any, now: float | None = None, small: Any = None) -> list[TriggerEvent]:
        """Process one frame. `small` lets tests pass a ready analysis copy."""
        now = time.monotonic() if now is None else now
        small = analysis_copy(frame, self.settings) if small is None else small
        previous, self._previous = self._previous, small
        if previous is None or previous.shape != small.shape:
            self._still_since = now
            self.state = "settling"
            return []

        self.motion = float(_changed(small, previous, self.settings.pixel_delta).mean())
        if self.motion > self.settings.motion_fraction:
            self._still_since = None
            self.state = "moving"
            return []
        if self._still_since is None:
            self._still_since = now
            self.state = "settling"
        if now - self._still_since < self.settings.still_seconds:
            return []

        first_settled_tick = self.state != "settled"
        self.state = "settled"
        if first_settled_tick:
            return self._on_settled(frame, small, now)
        if self._pending is not None:
            return self._retry_pending(frame, now)
        return []

    def _on_settled(self, frame: Any, small: np.ndarray, now: float) -> list[TriggerEvent]:
        delta = self.settings.pixel_delta
        enough = self.settings.min_change_pixels
        if self.empty is None or self._calibrate_next:
            self.empty = small
            self._calibrate_next = False
            self._reported = small
            return []
        if self._reported is not None:
            changed = _scene_diff(small, self._reported, delta)
            if _solid(changed).sum() < enough:
                return []  # same scene as before the hands came in
        else:
            changed = np.ones(small.shape[:2], dtype=bool)
        self._reported = small

        off_empty = _scene_diff(small, self.empty, delta)
        if _solid(off_empty).sum() < enough:
            self._pending = None
            self.empty = small  # follow slow lighting drift
            if not self.order_active:
                return []
            self.order_active = False
            self._submitted = None
            return [TriggerEvent("order_ended", now, self.order_number)]

        events: list[TriggerEvent] = []
        if not self.order_active:
            self.order_active = True
            self.order_number += 1
            self._submitted = None
            events.append(TriggerEvent("order_started", now, self.order_number))
            events += self._check(frame, now, "first", float(off_empty.mean()))
            return events

        if self._submitted is not None:
            changed = _scene_diff(small, self._submitted, delta)
            if _solid(changed).sum() < enough:
                self._pending = None  # changed back to what was already checked
                return []
        change = self._classify(small, changed)
        if change == "removed" and not self.settings.check_on_removal:
            self._pending = None  # a deferred check would now show the removal
            return []
        return self._check(frame, now, change, float(changed.mean()))

    def _classify(self, small: np.ndarray, changed: np.ndarray) -> ChangeKind:
        """Removed when the changed area now looks like bare mat; added when it didn't."""
        assert self.empty is not None
        if not changed.any():
            return "changed"
        bare_now = ~_scene_diff(small, self.empty, self.settings.pixel_delta)[changed]
        share = float(bare_now.mean())
        if share >= 0.8:
            return "removed"
        if share <= 0.2:
            return "added"
        return "changed"

    def _check(self, frame: Any, now: float, change: ChangeKind, fraction: float):
        event = TriggerEvent("check", now, self.order_number, frame, change, fraction)
        blocked = self.budget.blocked_reason(now)
        if blocked is None:
            return [self._spend(event)]
        if blocked == "cooldown":
            self._pending = event  # fire once the cooldown passes, if still settled
        return [TriggerEvent("suppressed", now, self.order_number, None, change, fraction, blocked)]

    def _retry_pending(self, frame: Any, now: float) -> list[TriggerEvent]:
        if self.budget.blocked_reason(now) is not None:
            return []
        event, self._pending = self._pending, None
        assert event is not None
        event.frame, event.at = frame, now
        return [self._spend(event)]

    def _spend(self, event: TriggerEvent) -> TriggerEvent:
        self.budget.spend(event.at)
        self._submitted = self._previous
        return event
