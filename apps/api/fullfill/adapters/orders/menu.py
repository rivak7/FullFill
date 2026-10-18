"""Durable FullFill menu in Square Catalog; never writes unrelated catalog items."""

import copy
import hashlib
import json
from collections.abc import Awaitable, Callable
from urllib.parse import quote, urlparse

from pydantic import ValidationError

from fullfill.application.menu_photo import MenuPhoto
from fullfill.application.order_source import MenuEdit, MenuEntry, MenuSnapshot, OrderSourceError

SquareRequest = Callable[[str, str, dict | None], Awaitable[dict]]
SquareImageUpload = Callable[[MenuPhoto, str], Awaitable[str]]


def menu_snapshot(items: list[MenuEntry]) -> MenuSnapshot:
    items = sorted(items, key=lambda item: (item.name.casefold(), item.item_id))
    encoded = json.dumps([item.model_dump() for item in items], sort_keys=True).encode()
    return MenuSnapshot(revision=hashlib.sha256(encoded).hexdigest(), items=items)


class SquareMenu:
    def __init__(self, request: SquareRequest, location_id: str, upload_photo: SquareImageUpload):
        self.request = request
        self.location_id = location_id
        self.upload_photo = upload_photo

    def _managed(self, obj: dict):
        for variation in obj.get("item_data", {}).get("variations", []):
            data = variation.get("item_variation_data", {})
            try:
                info = json.loads(data.get("user_data", "{}"))
            except (ValueError, TypeError):
                continue
            if (
                isinstance(info, dict)
                and info.get("ff") == 1
                and info.get("loc") == self.location_id
            ):
                yield variation, info

    def _entry(self, obj: dict, variation: dict, info: dict) -> MenuEntry:
        try:
            data = obj["item_data"]
            money = variation["item_variation_data"]["price_money"]
            return MenuEntry(
                item_id=info["id"],
                name=data["name"],
                description=data.get("description_plaintext", ""),
                price_cents=money["amount"],
                currency=money["currency"],
                verification_mode=info.get("check", "visible_item"),
                available=info.get("available", True),
                archived=data.get("is_archived", False),
                version=obj["version"],
                photo_id=next(iter(data.get("image_ids", [])), None),
            )
        except (KeyError, TypeError, ValidationError):
            raise OrderSourceError(
                "A menu item has unsupported data. Check its Square catalog entry."
            ) from None

    async def _objects(self) -> list[dict]:
        objects = []
        cursor = None
        seen = set()
        for _ in range(50):
            path = "/v2/catalog/list?types=ITEM"
            if cursor:
                path += "&cursor=" + quote(cursor, safe="")
            result = await self.request("GET", path, None)
            page = result.get("objects", [])
            if not isinstance(page, list) or any(not isinstance(obj, dict) for obj in page):
                raise OrderSourceError("Square returned an unreadable menu.")
            objects.extend(
                obj for obj in page if obj.get("type") == "ITEM" and not obj.get("is_deleted")
            )
            cursor = result.get("cursor")
            if not cursor:
                return objects
            if not isinstance(cursor, str) or cursor in seen:
                break
            seen.add(cursor)
        raise OrderSourceError("The menu could not be loaded completely. Try again.")

    async def snapshot(self) -> MenuSnapshot:
        items = [
            self._entry(obj, variation, info)
            for obj in await self._objects()
            for variation, info in self._managed(obj)
        ]
        if len({item.item_id for item in items}) != len(items):
            raise OrderSourceError("The Square menu contains duplicate FullFill item IDs.")
        image_ids = sorted({item.photo_id for item in items if item.photo_id})
        images = {}
        for start in range(0, len(image_ids), 1000):
            result = await self.request(
                "POST",
                "/v2/catalog/batch-retrieve",
                {
                    "object_ids": image_ids[start : start + 1000],
                },
            )
            for obj in result.get("objects", []):
                if obj.get("type") == "IMAGE" and not obj.get("is_deleted"):
                    url = obj.get("image_data", {}).get("url", "")
                    if (
                        isinstance(url, str)
                        and urlparse(url).scheme == "https"
                        and urlparse(url).netloc
                    ):
                        images[obj["id"]] = url
        for item in items:
            item.photo_url = images.get(item.photo_id)
        return menu_snapshot(items)

    async def save(
        self,
        edit: MenuEdit,
        key: str,
        *,
        verification_mode: str = "visible_item",
        require_photo: bool = True,
    ) -> MenuSnapshot:
        objects = await self._objects()
        matches = [
            (obj, variation, info)
            for obj in objects
            for variation, info in self._managed(obj)
            if info.get("id") == edit.item_id
        ]
        if len(matches) > 1:
            raise OrderSourceError("The menu contains duplicate item IDs.", 409)
        if matches:
            original, variation, info = matches[0]
            current = self._entry(original, variation, info)
            # An identical save can safely acknowledge a retry after a lost response.
            same_photo = edit.photo is None or (
                current.photo_id
                and info.get("photo_sha256") == edit.photo.digest
                and info.get("photo_id") == current.photo_id
            )
            if same_photo and all(
                getattr(current, field) == getattr(edit, field)
                for field in ("name", "price_cents", "available", "archived")
            ):
                return await self.snapshot()
            if current.version != edit.version:
                raise OrderSourceError(
                    "This item changed on another screen. Reload it before saving.", 409
                )
            obj = copy.deepcopy(original)
            variation, info = next((v, i) for v, i in self._managed(obj) if i["id"] == edit.item_id)
        else:
            if edit.version:
                raise OrderSourceError("This menu item no longer exists. Reload the menu.", 409)
            if require_photo and edit.photo is None:
                raise OrderSourceError("Add a photo before saving a new menu item.", 422)
            if len([1 for obj in objects for _ in self._managed(obj)]) >= 100:
                raise OrderSourceError("This demo supports up to 100 menu items.", 422)
            item_ref = "#item-" + edit.item_id
            variation = {
                "type": "ITEM_VARIATION",
                "id": "#variation-" + edit.item_id,
                "present_at_all_locations": False,
                "present_at_location_ids": [self.location_id],
                "item_variation_data": {
                    "item_id": item_ref,
                    "name": "Regular",
                    "pricing_type": "FIXED_PRICING",
                },
            }
            obj = {
                "type": "ITEM",
                "id": item_ref,
                "present_at_all_locations": False,
                "present_at_location_ids": [self.location_id],
                "item_data": {"variations": [variation]},
            }
            info = {
                "ff": 1,
                "loc": self.location_id,
                "id": edit.item_id,
                "check": verification_mode,
            }
        if edit.photo:
            image_id = await self.upload_photo(edit.photo, key)
            obj["item_data"]["image_ids"] = [image_id]
            info.update(photo_sha256=edit.photo.digest, photo_id=image_id)
        obj["item_data"].update(name=edit.name, is_archived=edit.archived)
        info["available"] = edit.available
        variation["item_variation_data"].update(
            price_money={"amount": edit.price_cents, "currency": "USD"},
            pricing_type="FIXED_PRICING",
            user_data=json.dumps(info, separators=(",", ":")),
        )
        await self.request("POST", "/v2/catalog/object", {"idempotency_key": key, "object": obj})
        return await self.snapshot()
