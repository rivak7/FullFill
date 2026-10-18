"""Sandbox order ingress. No payment calls or customer information are retained."""

import base64
import binascii
import hashlib
import hmac
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx
from fullfill_contracts.orders import OrderLine, OrderSnapshot
from pydantic import ValidationError

from fullfill.application.menu_photo import MenuPhoto
from fullfill.application.order_source import (
    CreateOrder,
    MenuEdit,
    MenuEntry,
    MenuSnapshot,
    OrderSourceError,
)

from .menu import SquareMenu, menu_snapshot


def demo_menu() -> list[MenuEntry]:
    data = json.loads(Path(__file__).with_name("demo-menu.json").read_text())
    return [MenuEntry.model_validate(item) for item in data]


class SquareOrders:
    base_url = "https://connect.squareupsandbox.com"
    queue_limit = 30

    def __init__(
        self,
        token: str,
        location_id: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        catalog: bool = False,
    ):
        self._token = token
        self.location_id = location_id
        self._transport = transport
        self._menu = {item.item_id: item for item in demo_menu()}
        self.catalog = (
            SquareMenu(self._request, location_id, self._upload_menu_photo) if catalog else None
        )

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
        return cls(token, location, catalog=True)

    async def _request(
        self, method: str, path: str, payload: dict | None = None, *, files: dict | None = None
    ) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=15,
                transport=self._transport,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Square-Version": "2026-09-16",
                },
            ) as client:
                response = (
                    await client.request(method, path, files=files)
                    if files
                    else await client.request(method, path, json=payload)
                )
        except httpx.RequestError:
            raise OrderSourceError(
                "Cannot reach Square. Check the backend connection and retry.", 503
            ) from None
        # Never forward Square's raw response, request headers, or credentials to browsers/logs.
        if response.status_code in (401, 403):
            raise OrderSourceError(
                "Square rejected the backend credentials. Check the Sandbox token and location.",
                503,
            )
        if response.status_code == 404:
            raise OrderSourceError("That item or order could not be found in Square.", 404)
        if response.status_code == 429:
            raise OrderSourceError("Square is busy. Wait a moment and retry.", 503)
        if response.status_code >= 400:
            try:
                errors = response.json().get("errors", [])
                if any(
                    error.get("code") in ("VERSION_MISMATCH", "OBJECT_VERSION_MISMATCH")
                    for error in errors
                ):
                    raise OrderSourceError(
                        "This item changed on another screen. Reload it before saving.", 409
                    )
            except (ValueError, AttributeError, TypeError):
                pass
            raise OrderSourceError("Square could not process this request. Retry the same change.")
        try:
            result = response.json()
            if not isinstance(result, dict) or result.get("errors"):
                raise ValueError
            return result
        except ValueError:
            raise OrderSourceError(
                "Square returned an unreadable response. Please retry."
            ) from None

    async def _upload_menu_photo(self, photo: MenuPhoto, key: str) -> str:
        # Upload unattached, then attach with the item's version-checked save. A
        # failed/stale save must never replace the photo on another screen's item.
        payload = {
            "idempotency_key": "ff-photo-"
            + hashlib.sha256(f"{self.location_id}/{key}".encode()).hexdigest(),
            "image": {
                "id": "#photo",
                "type": "IMAGE",
                "image_data": {"name": "FullFill menu photo"},
            },
        }
        extension = "jpg" if photo.content_type == "image/jpeg" else "png"
        result = await self._request(
            "POST",
            "/v2/catalog/images",
            files={
                "request": (None, json.dumps(payload), "application/json"),
                "file": (f"menu-photo.{extension}", photo.data, photo.content_type),
            },
        )
        image_id = result.get("image", {}).get("id")
        if not isinstance(image_id, str) or not image_id or image_id.startswith("#"):
            raise OrderSourceError("Square did not save the photo. Retry this change.")
        return image_id

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
                item_id = metadata.get("fullfill_item_id") or (
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
                        verification_mode=metadata.get("fullfill_verification_mode")
                        or (known.verification_mode if known else "visible_item"),
                    )
                )
            return OrderSnapshot(
                order_id=order["id"], revision=order.get("version", 1), lines=lines
            )
        except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation, ValidationError):
            raise OrderSourceError(
                "An order has unsupported item data. This demo requires positive whole-item quantities."
            ) from None

    async def _queue_records(self, *, limit: int | None = None) -> list[dict]:
        payload = {
            "location_ids": [self.location_id],
            "return_entries": False,
            "limit": 100,
            "query": {
                "filter": {"state_filter": {"states": ["OPEN"]}},
                "sort": {"sort_field": "CREATED_AT", "sort_order": "DESC"},
            },
        }
        orders: dict[str, dict] = {}
        seen_cursors = set()
        for _ in range(20):
            result = await self._request("POST", "/v2/orders/search", payload)
            page = result.get("orders", [])
            if not isinstance(page, list) or any(not isinstance(order, dict) for order in page):
                raise OrderSourceError("Square returned an unreadable queue. Please retry.")
            for order in page:
                # Empty orders aren't checkable tickets; terminal orders aren't pending work.
                if (
                    order.get("state") == "OPEN"
                    and order.get("line_items")
                    and (order.get("metadata") or {}).get("fullfill_queue_archived") != "true"
                ):
                    snapshot = self._snapshot(order)
                    orders[snapshot.order_id] = order
                    if limit and len(orders) == limit:
                        return list(orders.values())
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

    async def list_orders(self) -> list[OrderSnapshot]:
        return [
            self._snapshot(order) for order in await self._queue_records(limit=self.queue_limit)
        ]

    async def refresh_orders(self) -> list[OrderSnapshot]:
        orders = await self._queue_records()
        # Persist removal on Square, so an old ticket cannot reappear when newer
        # orders finish or a different browser/server handles the next refresh.
        for order in reversed(orders[self.queue_limit :]):
            await self._archive_from_queue(order)
        return [self._snapshot(order) for order in orders[: self.queue_limit]]

    async def _archive_from_queue(self, order: dict):
        for _ in range(3):
            if (
                order.get("state") != "OPEN"
                or (order.get("metadata") or {}).get("fullfill_queue_archived") == "true"
            ):
                return
            self._snapshot(order)  # Validate the location before any mutation.
            path = f"/v2/orders/{quote(order['id'], safe='')}"
            key = hashlib.sha256(
                f"queue-archive:{order['id']}:{order['version']}".encode()
            ).hexdigest()
            try:
                await self._request(
                    "PUT",
                    path,
                    {
                        "idempotency_key": key,
                        "order": {
                            "location_id": self.location_id,
                            "version": order["version"],
                            "metadata": {
                                **(order.get("metadata") or {}),
                                "fullfill_queue_archived": "true",
                            },
                        },
                    },
                )
                return
            except OrderSourceError as error:
                if error.status_code != 409:
                    raise
                result = await self._request("GET", path)
                order = result.get("order", {})
        raise OrderSourceError("The queue changed during cleanup. Refresh to try again.", 503)

    async def get_order(self, order_id: str) -> OrderSnapshot:
        result = await self._request("GET", f"/v2/orders/{quote(order_id, safe='')}")
        return self._snapshot(result.get("order", {}))

    async def menu(self) -> MenuSnapshot:
        return (
            await self.catalog.snapshot()
            if self.catalog
            else menu_snapshot(list(self._menu.values()))
        )

    async def save_menu(self, edit: MenuEdit, idempotency_key: str) -> MenuSnapshot:
        if not self.catalog:
            raise OrderSourceError("Square menu editing is not configured.", 503)
        return await self.catalog.save(edit, idempotency_key)

    def _order_payload(
        self, request: CreateOrder, idempotency_key: str, menu: dict[str, MenuEntry]
    ) -> dict:
        lines = []
        for requested in sorted(request.items, key=lambda item: item.item_id):
            item = menu.get(requested.item_id)
            if item is None or item.archived or not item.available:
                raise OrderSourceError("That menu item is unavailable. Refresh the menu.", 422)
            lines.append(
                {
                    "name": item.name,
                    "quantity": str(requested.quantity),
                    "metadata": {
                        "fullfill_item_id": item.item_id,
                        "fullfill_verification_mode": item.verification_mode,
                    },
                    "base_price_money": {"amount": item.price_cents, "currency": item.currency},
                }
            )
        return {
            "idempotency_key": idempotency_key,
            "order": {
                "location_id": self.location_id,
                "reference_id": f"FF-{idempotency_key[:32]}",
                "state": "OPEN",
                "line_items": lines,
            },
        }

    def _signature(self, encoded: str) -> str:
        return hmac.new(
            self._token.encode(), ("fullfill-quote-v1:" + encoded).encode(), hashlib.sha256
        ).hexdigest()

    async def prepare_order(self, request: CreateOrder, idempotency_key: str) -> CreateOrder:
        snapshot = await self.menu()
        if request.menu_revision != snapshot.revision:
            raise OrderSourceError("The menu changed. Review your order and try again.", 409)
        payload = self._order_payload(
            request, idempotency_key, {item.item_id: item for item in snapshot.items}
        )
        approved = {"items": [item.model_dump() for item in request.items], "payload": payload}
        encoded = base64.urlsafe_b64encode(
            json.dumps(approved, sort_keys=True, separators=(",", ":")).encode()
        ).decode()
        return request.model_copy(update={"quote": encoded + "." + self._signature(encoded)})

    async def create_order(self, request: CreateOrder, idempotency_key: str) -> OrderSnapshot:
        if request.quote:
            try:
                encoded, signature = request.quote.rsplit(".", 1)
                if not hmac.compare_digest(signature, self._signature(encoded)):
                    raise ValueError
                approved = json.loads(base64.urlsafe_b64decode(encoded))
                payload = approved["payload"]
                if (
                    payload["idempotency_key"] != idempotency_key
                    or payload["order"]["location_id"] != self.location_id
                    or approved["items"] != [item.model_dump() for item in request.items]
                ):
                    raise ValueError
            except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError):
                raise OrderSourceError(
                    "This checkout could not be verified. Reload the menu.", 422
                ) from None
        else:
            if self.catalog:
                raise OrderSourceError("Refresh this website before placing an order.", 422)
            payload = self._order_payload(request, idempotency_key, self._menu)
        # Prepared checkouts are immutable. Retrying after a menu edit sends exactly the
        # same Square request/key, even across independent serverless instances.
        result = await self._request("POST", "/v2/orders", payload)
        return self._snapshot(result.get("order", {}))
