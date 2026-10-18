"""Rebuild once per warm process, then fetch only recently changed Square orders.

Square remains authoritative. Cache misses rebuild every page, including old
unresolved tickets; archived tickets are discarded rather than retained in RAM.
"""

import asyncio
import copy
import time
from datetime import UTC, datetime

from fullfill.application.order_source import OrderSourceError


class SquareQueue:
    def init_queue_cache(self, enabled):
        self._queue_cache_enabled = enabled
        self._queue_lock = asyncio.Lock()
        self._queue_orders = None
        self._queue_removed = {}
        self._queue_mutations = {}
        self._queue_synced = 0.0
        self._queue_built = 0.0

    def _remember_order(self, order, *, local=False):
        if local and order.get("id"):
            self._queue_mutations[order["id"]] = (time.time(), copy.deepcopy(order))
        if self._queue_orders is None or not order.get("id"):
            return
        order_id, version = order["id"], order.get("version", 0)
        previous = self._queue_orders.get(order_id, {})
        deleted_version = self._queue_removed.get(order_id, (0, 0))[0]
        if version < max(previous.get("version", 0), deleted_version):
            return
        if (
            order.get("state") == "OPEN"
            and order.get("line_items")
            and (order.get("metadata") or {}).get("fullfill_queue_archived") != "true"
        ):
            self._queue_orders[order_id] = copy.deepcopy(order)
            self._queue_removed.pop(order_id, None)
        else:
            self._queue_orders.pop(order_id, None)
            self._queue_removed[order_id] = (version, time.time())

    async def _search_queue(self, since=None):
        filters = {"state_filter": {"states": ["OPEN"]}}
        sort_field = "CREATED_AT"
        if since is not None:
            # Include closed/cancelled orders so they can leave the cached queue.
            # Overlap handles writes racing a search and ordinary indexing delay.
            filters = {
                "date_time_filter": {
                    "updated_at": {
                        "start_at": datetime.fromtimestamp(max(0, since - 120), UTC).isoformat()
                    }
                }
            }
            sort_field = "UPDATED_AT"
        payload = {
            "location_ids": [self.location_id],
            "return_entries": False,
            "limit": 1000,
            "query": {"filter": filters, "sort": {"sort_field": sort_field, "sort_order": "ASC"}},
        }
        seen = set()
        records = {}
        while True:
            result = await self._request("POST", "/v2/orders/search", payload)
            page = result.get("orders", [])
            if not isinstance(page, list) or any(not isinstance(order, dict) for order in page):
                raise OrderSourceError("Square returned an unreadable queue. Please retry.")
            for order in page:
                if not order.get("id"):
                    raise OrderSourceError("Square returned an unreadable order. Please retry.")
                # A cold scan never accumulates archived history in memory.
                if since is None and (
                    (order.get("metadata") or {}).get("fullfill_queue_archived") == "true"
                    or order.get("state") != "OPEN"
                    or not order.get("line_items")
                ):
                    continue
                if order.get("line_items"):
                    self._snapshot(order)  # Validate location and supported data.
                previous = records.get(order["id"], {})
                if order.get("version", 0) >= previous.get("version", 0):
                    records[order["id"]] = order
            cursor = result.get("cursor")
            if not cursor:
                return records
            if not isinstance(cursor, str) or cursor in seen:
                raise OrderSourceError("Square returned an invalid queue cursor. Please retry.")
            seen.add(cursor)
            payload["cursor"] = cursor

    async def _queue_records(self):
        if not self._queue_cache_enabled:
            return list((await self._search_queue()).values())
        async with self._queue_lock:
            now = time.time()
            if self._queue_orders is not None and now - self._queue_synced < 0.75:
                return copy.deepcopy(
                    sorted(
                        self._queue_orders.values(),
                        key=lambda order: (order.get("created_at", ""), order["id"]),
                    )
                )
            rebuild = self._queue_orders is None or now - self._queue_built > 600
            records = await self._search_queue(None if rebuild else self._queue_synced)
            # Do not advance the cursor or publish a partial queue after a failed page.
            if rebuild:
                self._queue_orders = {}
                self._queue_built = now
            # Retain acknowledged local writes while Square's search catches up.
            self._queue_mutations = {
                key: value for key, value in self._queue_mutations.items() if value[0] >= now - 120
            }
            for _, order in self._queue_mutations.values():
                if order.get("version", 0) >= records.get(order["id"], {}).get("version", 0):
                    records[order["id"]] = order
            for order in records.values():
                self._remember_order(order)
            self._queue_synced = now
            self._queue_removed = {
                key: value for key, value in self._queue_removed.items() if value[1] >= now - 600
            }
            return copy.deepcopy(
                sorted(
                    self._queue_orders.values(),
                    key=lambda order: (order.get("created_at", ""), order["id"]),
                )
            )
