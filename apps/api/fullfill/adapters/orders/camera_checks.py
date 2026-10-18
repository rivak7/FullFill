"""Small, shared check records in Square; camera images are never persisted.

Version-checked reservations prevent two API instances from paying for the same
attempt. A reservation is consumed even if the provider fails or the response is
lost. Retrying a paid call is always an explicit new attempt.
"""

import hashlib
import json
import time
import zlib
from datetime import UTC, datetime
from urllib.parse import quote

from fullfill_contracts.checks import CheckResult
from fullfill_contracts.vision import Observations, TargetObservation, UnexpectedItem

from fullfill.application.order_source import OrderSourceError
from fullfill.domain.compare_order import compare_order, targets_for
from fullfill.domain.vision_uncertainty import REASON_CODES, REASONS

from .check_storage import pack_result, unpack_result
from .claims import CLAIM_KEY, claim_value, require_worker

CHECK_KEY = "fullfill_camera_check"
CONFIRM_SECONDS = 15
LEASE_SECONDS = 90
COMPLETED_AT_KEY = "fullfill_completed_at"
UNDO_SECONDS = 120
STORED_REASONS = {REASON_CODES[key]: value for key, value in REASONS.items()}


def read_record(metadata):
    try:
        return json.loads(metadata.get(CHECK_KEY, "{}"))
    except (TypeError, ValueError):
        return {}


def check_result(order, metadata, lines=()):
    record = read_record(metadata)
    if not record or record.get("s") == "cancelled":
        return None
    status = record["s"]
    if status == "running" and time.time() - record["t"] > LEASE_SECONDS:
        status = "failed"
    if status == "awaiting_confirmation" and time.time() - record["t"] > CONFIRM_SECONDS:
        status = "superseded"
    comparison = None
    if status == "completed":
        try:
            data = unpack_result(metadata, lines, record.get("r", 2))
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
                        reason=STORED_REASONS.get(
                            entry[2] if len(entry) > 2 else "u", REASONS["unknown"]
                        )
                        if entry[0] == "u"
                        else None,
                    )
                    for target, entry in zip(targets, data["o"], strict=True)
                ],
                unexpected_items=[
                    UnexpectedItem(name=item)
                    if isinstance(item, str)
                    else UnexpectedItem(name=item[0], quantity=item[1])
                    for item in data["u"]
                ],
                scene_uncertainty=data.get("s"),
            )
            comparison = compare_order(order, observations)
        except (IndexError, KeyError, TypeError, ValueError, zlib.error):
            status = "failed"
    disposition = (
        {"pass": "verified", "fail": "pending", "unsure": "needs_review"}[comparison.verdict]
        if comparison
        else "needs_review"
        if status in ("failed", "superseded")
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
        error_code="scene_changed"
        if status == "superseded"
        else "vision_unavailable"
        if status == "failed"
        else None,
    )


class SquareCameraChecks:
    async def reserve_camera_check(self, order_id, revision, image_digest, request_key, worker_id):
        path = f"/v2/orders/{quote(order_id, safe='')}"
        order = (await self._request("GET", path)).get("order", {})
        state = self._order_state(order)
        metadata = order.get("metadata") or {}
        require_worker(order, worker_id)
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
                        CLAIM_KEY: claim_value(worker_id),
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
        record["s"] = "failed" if observations is None else "awaiting_confirmation"
        patches = []
        if observations is not None:
            compare_order(self._snapshot(reserved), observations)  # Validate before compacting.
            by_id = {entry.target_id: entry for entry in observations.targets}
            values = []
            for target in targets_for(self._snapshot(reserved)):
                entry = by_id[target.target_id]
                if entry.observed_quantity is not None and entry.observed_quantity > 100000:
                    raise ValueError("Invalid observed quantity")
                value = [
                    "u" if observations.scene_uncertainty else entry.status[0],
                    entry.observed_quantity,
                ]
                if entry.status == "unsure":
                    value.append(
                        next(
                            (
                                code
                                for code, reason in STORED_REASONS.items()
                                if reason == entry.reason
                            ),
                            "u",
                        )
                    )
                values.append(value)
            payload = {
                "o": values,
                "u": [[item.name, item.quantity] for item in observations.unexpected_items],
            }
            if observations.scene_uncertainty:
                payload["s"] = observations.scene_uncertainty
            record["r"], patches = pack_result(payload, metadata, reserved.get("line_items", []))
        record["t"] = int(time.time())
        metadata[COMPLETED_AT_KEY] = "0"
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
                    **({"line_items": patches} if patches else {}),
                    "metadata": metadata,
                },
            },
        )
        return self._order_state(result.get("order", {}))

    async def confirm_camera_check(self, order_id, check_id, revision, worker_id, scene_unchanged):
        path = f"/v2/orders/{quote(order_id, safe='')}"
        order = (await self._request("GET", path)).get("order", {})
        state = self._order_state(order)
        require_worker(order, worker_id)
        metadata = dict(order.get("metadata") or {})
        record = read_record(metadata)
        if (
            order.get("state") != "OPEN"
            or metadata.get("fullfill_queue_archived") == "true"
            or not state.current_check
            or record.get("k") != check_id
        ):
            raise OrderSourceError("This check is no longer current. Take a new photo.", 409)
        if record.get("s") == "superseded" or (scene_unchanged and record.get("s") == "completed"):
            return state
        if order["version"] != revision or record.get("s") not in (
            "awaiting_confirmation",
            "completed",
        ):
            raise OrderSourceError("This order changed. Refresh before checking it.", 409)
        # A missing browser confirmation never becomes a green result.
        expired = time.time() - record["t"] > CONFIRM_SECONDS
        record["s"] = "completed" if scene_unchanged and not expired else "superseded"
        metadata[CHECK_KEY] = json.dumps(record, separators=(",", ":"))
        candidate = self._order_state({**order, "metadata": metadata})
        metadata[COMPLETED_AT_KEY] = str(
            int(time.time()) if candidate.disposition == "verified" else 0
        )
        key = hashlib.sha256(
            f"confirm:{check_id}:{revision}:{scene_unchanged}".encode()
        ).hexdigest()
        result = await self._request(
            "PUT",
            path,
            {
                "idempotency_key": key,
                "order": {
                    "location_id": self.location_id,
                    "version": revision,
                    "metadata": metadata,
                },
            },
        )
        return self._order_state(result.get("order", {}))
