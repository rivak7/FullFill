"""Order reservations shared through version-checked Square metadata."""

import hashlib
import json
import time
from urllib.parse import quote

from fullfill_contracts.events import OrderClaim

from fullfill.application.order_source import OrderSourceError

CLAIM_KEY = "fullfill_worker"
CLAIM_SECONDS = 120


def read_claim(metadata):
    try:
        value = json.loads(metadata.get(CLAIM_KEY, "null"))
        if isinstance(value, dict) and value["until"] > time.time():
            return OrderClaim(worker_id=value["id"], expires_at=value["until"])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def claim_value(worker_id):
    return json.dumps(
        {"id": worker_id, "until": int(time.time()) + CLAIM_SECONDS}, separators=(",", ":")
    )


def require_worker(order, worker_id):
    claim = read_claim(order.get("metadata") or {})
    if not claim or claim.worker_id != worker_id:
        raise OrderSourceError(
            "This order is not reserved by this screen. Select an available order.", 409
        )


class SquareClaims:
    async def claim_order(self, order_id, edit):
        path = f"/v2/orders/{quote(order_id, safe='')}"
        order = (await self._request("GET", path)).get("order", {})
        state = self._order_state(order)
        metadata = dict(order.get("metadata") or {})
        claim = state.claim
        if edit.release and (not claim or claim.worker_id != edit.worker_id):
            return state
        if claim and claim.worker_id != edit.worker_id:
            raise OrderSourceError("Another screen is working on this order.", 409)
        if order.get("state") != "OPEN" or metadata.get("fullfill_queue_archived") == "true":
            raise OrderSourceError("This order is no longer in the queue.", 409)
        if not edit.release and claim and claim.expires_at - time.time() > 60:
            return state  # Polls and lost-response retries do not create extra writes.
        if state.order.revision != edit.expected_revision:
            raise OrderSourceError("This order changed. Refresh before reserving it.", 409)
        metadata[CLAIM_KEY] = "null" if edit.release else claim_value(edit.worker_id)
        key = hashlib.sha256(
            f"claim:{order_id}:{edit.worker_id}:{order['version']}:{edit.release}".encode()
        ).hexdigest()
        result = await self._request(
            "PUT",
            path,
            {
                "idempotency_key": key,
                "order": {
                    "location_id": self.location_id,
                    "version": order["version"],
                    "metadata": metadata,
                },
            },
        )
        return self._order_state(result.get("order", {}))
