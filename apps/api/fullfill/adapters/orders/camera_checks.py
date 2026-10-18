"""Small, shared check records in Square; camera images are never persisted.

Version-checked reservations prevent two API instances from paying for the same
attempt. A reservation is consumed even if the provider fails or the response is
lost. Retrying a paid call is always an explicit new attempt.
"""

import hashlib
import json
import time
from datetime import UTC, datetime
from urllib.parse import quote

from fullfill_contracts.checks import CheckResult
from fullfill_contracts.vision import Observations, TargetObservation, UnexpectedItem

from fullfill.application.order_source import OrderSourceError
from fullfill.domain.compare_order import compare_order, targets_for

CHECK_KEY = "fullfill_camera_check"
RESULT_KEYS = ("fullfill_camera_result_0", "fullfill_camera_result_1")
MAX_CHECKS_PER_ORDER = 20
COOLDOWN_SECONDS = 10
LEASE_SECONDS = 90


def read_record(metadata):
    try:
        return json.loads(metadata.get(CHECK_KEY, "{}"))
    except (TypeError, ValueError):
        return {}


def check_result(order, metadata):
    record = read_record(metadata)
    if not record or record.get("s") == "cancelled":
        return None
    status = record["s"]
    if status == "running" and time.time() - record["t"] > LEASE_SECONDS:
        status = "failed"
    comparison = None
    if status == "completed":
        try:
            data = json.loads("".join(metadata.get(key, "") for key in RESULT_KEYS))
            targets = targets_for(order)
            if len(data["o"]) != len(targets):
                raise ValueError
            observations = Observations(
                capture_id=record["k"],
                targets=[
                    TargetObservation(
                        target_id=target.target_id,
                        status={"p": "present", "m": "missing", "u": "unsure"}[entry[0]],
                        observed_quantity=entry[1],
                        reason="not clearly visible or distinguishable"
                        if entry[0] == "u"
                        else None,
                    )
                    for target, entry in zip(targets, data["o"], strict=True)
                ],
                unexpected_items=[UnexpectedItem(name=name) for name in data["u"]],
            )
            comparison = compare_order(order, observations)
        except (KeyError, TypeError, ValueError):
            status = "failed"
    disposition = (
        {"pass": "verified", "fail": "pending", "unsure": "needs_review"}[comparison.verdict]
        if comparison
        else "pending"
    )
    return CheckResult(
        check_id=record["k"],
        capture_id=record["k"],
        order_id=order.order_id,
        order_revision=order.revision,
        execution_status=status,
        disposition=disposition,
        disposition_revision=order.revision,
        verdict=comparison.verdict if comparison else None,
        discrepancies=comparison.discrepancies if comparison else [],
        completed_at=datetime.fromtimestamp(record["t"], UTC) if status == "completed" else None,
        error_code="vision_unavailable" if status == "failed" else None,
    )


class SquareCameraChecks:
    async def reserve_camera_check(self, order_id, revision, image_digest, request_key):
        path = f"/v2/orders/{quote(order_id, safe='')}"
        order = (await self._request("GET", path)).get("order", {})
        state = self._order_state(order)
        metadata = order.get("metadata") or {}
        previous = read_record(metadata)
        key = hashlib.sha256(f"camera:{order_id}:{request_key}".encode()).hexdigest()
        if previous.get("k") == key:
            if previous.get("d") != image_digest:
                raise OrderSourceError("This check ID was already used for a different photo.", 409)
            # No duplicate model call, including after a timeout or function restart.
            return None, state
        if (
            state.order.revision != revision
            or order.get("state") != "OPEN"
            or metadata.get("fullfill_queue_archived") == "true"
        ):
            raise OrderSourceError("This order changed. Refresh before checking it.", 409)
        if state.disposition in ("verified", "overridden"):
            raise OrderSourceError("Reopen this order before checking it again.", 409)
        now = int(time.time())
        if previous.get("s") == "running" and now - previous["t"] < LEASE_SECONDS:
            raise OrderSourceError("This order is already being checked on another screen.", 409)
        if previous.get("n", 0) >= MAX_CHECKS_PER_ORDER:
            raise OrderSourceError("This order reached its 20-check limit. Check it manually.", 429)
        if previous and now - previous["t"] < COOLDOWN_SECONDS:
            raise OrderSourceError("Wait 10 seconds between camera checks.", 429)
        record = {
            "k": key,
            "d": image_digest,
            "n": previous.get("n", 0) + 1,
            "t": now,
            "s": "running",
        }
        saved = await self._request(
            "PUT",
            path,
            {
                "idempotency_key": key,
                "order": {
                    "location_id": self.location_id,
                    "version": revision,
                    "metadata": {
                        **metadata,
                        CHECK_KEY: json.dumps(record, separators=(",", ":")),
                        "fullfill_queue_status": "unfulfilled",
                        "fullfill_status_fingerprint": self._ticket_fingerprint(order),
                        "fullfill_status_request": key,
                    },
                },
            },
        )
        reserved = saved.get("order", {})
        return reserved, self._order_state(reserved)

    async def finish_camera_check(self, reserved, observations=None):
        metadata = dict(reserved.get("metadata") or {})
        record = read_record(metadata)
        record["s"] = "failed" if observations is None else "completed"
        if observations is not None:
            by_id = {entry.target_id: entry for entry in observations.targets}
            values = []
            for target in targets_for(self._snapshot(reserved)):
                entry = by_id[target.target_id]
                if entry.observed_quantity is not None and entry.observed_quantity > 100000:
                    raise ValueError("Invalid observed quantity")
                values.append([entry.status[0], entry.observed_quantity])
            # Keep within Square's two 255-character values. Names are display
            # hints only; retaining any unexpected item preserves the verdict.
            extras = [item.name[:100] for item in observations.unexpected_items[:1]]
            packed = json.dumps(
                {"o": values, "u": extras}, separators=(",", ":"), ensure_ascii=False
            )
            if len(packed) > 510:
                raise ValueError("Check result exceeds the demo storage limit")
            for index, result_key in enumerate(RESULT_KEYS):
                metadata[result_key] = packed[index * 255 : (index + 1) * 255]
        record["t"] = int(time.time())
        metadata[CHECK_KEY] = json.dumps(record, separators=(",", ":"))
        # An edit or manual decision while inference runs must win. Never retry
        # this write with a fresh revision or re-run the paid model call.
        result = await self._request(
            "PUT",
            f"/v2/orders/{quote(reserved['id'], safe='')}",
            {
                "idempotency_key": f"camera-finish-{record['k']}",
                "order": {
                    "location_id": self.location_id,
                    "version": reserved["version"],
                    "metadata": metadata,
                },
            },
        )
        return self._order_state(result.get("order", {}))
