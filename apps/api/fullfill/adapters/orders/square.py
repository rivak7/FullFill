"""Sandbox order ingress. No payment calls or customer information are retained."""

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx
from fullfill_contracts.orders import OrderLine, OrderSnapshot
from pydantic import ValidationError

from fullfill.application.order_source import CreateOrder, MenuEntry, OrderSourceError


def demo_menu() -> list[MenuEntry]:
    data = json.loads(Path(__file__).with_name("demo-menu.json").read_text())
    return [MenuEntry.model_validate(item) for item in data]


class SquareOrders:
    base_url = "https://connect.squareupsandbox.com"

    def __init__(
        self,
        token: str,
        location_id: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._token = token
        self.location_id = location_id
        self._transport = transport
        self._menu = {item.item_id: item for item in demo_menu()}

    @classmethod
    def from_env(cls):
        if os.getenv("SQUARE_ENVIRONMENT", "sandbox").lower() != "sandbox":
            raise OrderSourceError("This demo connector requires SQUARE_ENVIRONMENT=sandbox.", 503)
        token = os.getenv("SQUARE_ACCESS_TOKEN", "").strip()
        location = os.getenv("SQUARE_LOCATION_ID", "").strip()
        if not token or not location:
            raise OrderSourceError(
                "Square is not configured. Set SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID "
                "on the backend, then restart it.",
                503,
            )
        return cls(token, location)

    async def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=15,
                transport=self._transport,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Square-Version": "2026-09-16",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.request(method, path, json=payload)
        except httpx.RequestError:
            raise OrderSourceError(
                "Cannot reach Square. Check the backend connection and retry the same order.", 503
            ) from None
        # Never forward Square's raw response, request headers, or credentials to browsers/logs.
        if response.status_code in (401, 403):
            raise OrderSourceError(
                "Square rejected the backend credentials. Check the Sandbox token and location.",
                503,
            )
        if response.status_code == 404:
            raise OrderSourceError("That order could not be found in Square.", 404)
        if response.status_code == 429:
            raise OrderSourceError("Square is busy. Wait a moment and retry.", 503)
        if response.status_code >= 400:
            raise OrderSourceError(
                "Square could not process this request. Retry with the same order."
            )
        try:
            result = response.json()
            if not isinstance(result, dict) or result.get("errors"):
                raise ValueError
            return result
        except ValueError:
            raise OrderSourceError(
                "Square returned an unreadable response. Please retry."
            ) from None

    def _snapshot(self, order: dict) -> OrderSnapshot:
        if not isinstance(order, dict):
            raise OrderSourceError("Square returned an unreadable order. Please retry.")
        if order.get("location_id") != self.location_id:
            raise OrderSourceError("That order does not belong to this location.", 404)
        try:
            lines = []
            for index, line in enumerate(order.get("line_items", [])):
                quantity = Decimal(line["quantity"])
                if (
                    not quantity.is_finite()
                    or quantity <= 0
                    or quantity > 100000
                    or quantity != quantity.to_integral_value()
                    or line.get("quantity_unit") is not None
                ):
                    raise ValueError
                name = line.get("name") or "Unnamed item"
                metadata = line.get("metadata") or {}
                known = self._menu.get(metadata.get("fullfill_item_id"))
                if known is None and not line.get("catalog_object_id"):
                    known = next(
                        (
                            item
                            for item in self._menu.values()
                            if item.name.casefold() == name.casefold()
                        ),
                        None,
                    )
                line_id = line.get("uid") or f"line-{index}"
                item_id = (
                    known.item_id
                    if known
                    else (f"square:{line.get('catalog_object_id') or order['id'] + ':' + line_id}")
                )
                # Keep visible variation/modifier information on the ticket.
                additions = [line.get("variation_name"), line.get("note")]
                additions.extend(modifier.get("name") for modifier in line.get("modifiers", []))
                details = [value for value in additions if value]
                lines.append(
                    OrderLine(
                        line_id=line_id,
                        item_id=item_id,
                        name=name + (" — " + ", ".join(details) if details else ""),
                        quantity=int(quantity),
                        verification_mode=known.verification_mode if known else "visible_item",
                    )
                )
            return OrderSnapshot(
                order_id=order["id"], revision=order.get("version", 1), lines=lines
            )
        except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation, ValidationError):
            raise OrderSourceError(
                "An order has unsupported item data. This demo requires positive whole-item quantities."
            ) from None

    async def list_orders(self) -> list[OrderSnapshot]:
        payload = {
            "location_ids": [self.location_id],
            "return_entries": False,
            "limit": 100,
            "query": {
                "filter": {"state_filter": {"states": ["OPEN"]}},
                "sort": {"sort_field": "CREATED_AT", "sort_order": "DESC"},
            },
        }
        orders: dict[str, OrderSnapshot] = {}
        seen_cursors = set()
        for _ in range(20):
            result = await self._request("POST", "/v2/orders/search", payload)
            page = result.get("orders", [])
            if not isinstance(page, list) or any(not isinstance(order, dict) for order in page):
                raise OrderSourceError("Square returned an unreadable queue. Please retry.")
            for order in page:
                # Empty orders aren't checkable tickets; terminal orders aren't pending work.
                if order.get("state") == "OPEN" and order.get("line_items"):
                    snapshot = self._snapshot(order)
                    orders[snapshot.order_id] = snapshot
            cursor = result.get("cursor")
            if not cursor:
                return list(orders.values())
            if not isinstance(cursor, str):
                raise OrderSourceError("Square returned an unreadable queue cursor. Please retry.")
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            payload["cursor"] = cursor
        raise OrderSourceError("The order queue is too large to load completely. Try again later.")

    async def get_order(self, order_id: str) -> OrderSnapshot:
        result = await self._request("GET", f"/v2/orders/{quote(order_id, safe='')}")
        return self._snapshot(result.get("order", {}))

    async def create_order(self, request: CreateOrder, idempotency_key: str) -> OrderSnapshot:
        lines = []
        for requested in sorted(request.items, key=lambda item: item.item_id):
            item = self._menu.get(requested.item_id)
            if item is None:
                raise OrderSourceError("That menu item is unavailable. Refresh the menu.", 422)
            lines.append(
                {
                    "name": item.name,
                    "quantity": str(requested.quantity),
                    "metadata": {"fullfill_item_id": item.item_id},
                    "base_price_money": {"amount": item.price_cents, "currency": item.currency},
                }
            )
        result = await self._request(
            "POST",
            "/v2/orders",
            {
                "idempotency_key": idempotency_key,
                "order": {
                    "location_id": self.location_id,
                    "reference_id": f"FF-{idempotency_key[:32]}",
                    "state": "OPEN",
                    "line_items": lines,
                },
            },
        )
        return self._snapshot(result.get("order", {}))
