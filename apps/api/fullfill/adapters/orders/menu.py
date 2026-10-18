"""Durable FullFill menu in Square Catalog; never writes unrelated catalog items."""

import copy
import hashlib
import json
from collections.abc import Awaitable, Callable
from urllib.parse import quote, urlparse

from pydantic import ValidationError

from fullfill.application.menu_photo import MenuPhoto
from fullfill.application.order_source import (
    MenuCategory,
    MenuEdit,
    MenuEntry,
    MenuSnapshot,
    OrderSourceError,
)

SquareRequest = Callable[[str, str, dict | None], Awaitable[dict]]
SquareImageUpload = Callable[[MenuPhoto, str], Awaitable[str]]


def menu_snapshot(
    items: list[MenuEntry], categories: list[MenuCategory] | None = None
) -> MenuSnapshot:
    items = sorted(items, key=lambda item: (item.name.casefold(), item.item_id))
    categories = sorted(categories or [], key=lambda c: (c.name.casefold(), c.category_id))
    encoded = json.dumps(
        [[item.model_dump() for item in items], [c.model_dump() for c in categories]],
        sort_keys=True,
    ).encode()
    return MenuSnapshot(
        revision=hashlib.sha256(encoded).hexdigest(), items=items, categories=categories
    )


def _category_of(data: dict) -> str | None:
    listed = data.get("categories")
    if isinstance(listed, list) and listed and isinstance(listed[0], dict):
        return listed[0].get("id")
    return data.get("category_id")


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
                category_id=_category_of(data),
            )
        except (KeyError, TypeError, ValidationError):
            raise OrderSourceError(
                "A menu item has unsupported data. Check its Square catalog entry."
            ) from None

    def _categories(self, objects: list[dict]) -> list[MenuCategory]:
        # Square categories are shared with the restaurant's own catalog, so every
        # category offered at this location is listed; FullFill only ever adds one.
        categories = []
        for obj in objects:
            name = obj.get("category_data", {}).get("name")
            at_location = obj.get("present_at_all_locations", True) or self.location_id in (
                obj.get("present_at_location_ids") or []
            )
            if obj.get("type") == "CATEGORY" and at_location and isinstance(name, str) and name:
                categories.append(MenuCategory(category_id=obj["id"], name=name))
        return categories

    async def _objects(self) -> list[dict]:
        objects = []
        cursor = None
        seen = set()
        for _ in range(50):
            path = "/v2/catalog/list?types=ITEM,CATEGORY"
            if cursor:
                path += "&cursor=" + quote(cursor, safe="")
            result = await self.request("GET", path, None)
            page = result.get("objects", [])
            if not isinstance(page, list) or any(not isinstance(obj, dict) for obj in page):
                raise OrderSourceError("Square returned an unreadable menu.")
            objects.extend(
                obj
                for obj in page
                if obj.get("type") in ("ITEM", "CATEGORY") and not obj.get("is_deleted")
            )
            cursor = result.get("cursor")
            if not cursor:
                return objects
            if not isinstance(cursor, str) or cursor in seen:
                break
            seen.add(cursor)
        raise OrderSourceError("The menu could not be loaded completely. Try again.")

    async def snapshot(self) -> MenuSnapshot:
        objects = await self._objects()
        categories = self._categories(objects)
        known = {category.category_id for category in categories}
        items = [
            self._entry(obj, variation, info)
            for obj in objects
            for variation, info in self._managed(obj)
        ]
        for item in items:
            if item.category_id not in known:
                item.category_id = None
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
        return menu_snapshot(items, categories)

    async def add_category(self, name: str, key: str) -> MenuSnapshot:
        categories = self._categories(await self._objects())
        # Adding a name that already exists (or retrying) just returns the menu.
        if any(category.name.casefold() == name.casefold() for category in categories):
            return await self.snapshot()
        if len(categories) >= 30:
            raise OrderSourceError("This demo supports up to 30 categories.", 422)
        category = {
            "type": "CATEGORY",
            "id": "#category",
            "present_at_all_locations": False,
            "present_at_location_ids": [self.location_id],
            "category_data": {"name": name},
        }
        await self.request(
            "POST", "/v2/catalog/object", {"idempotency_key": key, "object": category}
        )
        return await self.snapshot()

    async def save(
        self,
        edit: MenuEdit,
        key: str,
        *,
        verification_mode: str = "visible_item",
        require_photo: bool = True,
    ) -> MenuSnapshot:
        objects = await self._objects()
        if edit.category_id and edit.category_id not in {
            category.category_id for category in self._categories(objects)
        }:
            raise OrderSourceError("That category was removed. Pick another one.", 409)
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
                for field in ("name", "price_cents", "available", "archived", "category_id")
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
        obj["item_data"].pop("category_id", None)  # Square's older single-category field
        if edit.category_id:
            obj["item_data"]["categories"] = [{"id": edit.category_id}]
            obj["item_data"]["reporting_category"] = {"id": edit.category_id}
        else:
            obj["item_data"].pop("categories", None)
            obj["item_data"].pop("reporting_category", None)
        info["available"] = edit.available
        variation["item_variation_data"].update(
            price_money={"amount": edit.price_cents, "currency": "USD"},
            pricing_type="FIXED_PRICING",
            user_data=json.dumps(info, separators=(",", ":")),
        )
        await self.request("POST", "/v2/catalog/object", {"idempotency_key": key, "object": obj})
        return await self.snapshot()
