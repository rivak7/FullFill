"""Menu persistence, checkout price consistency, and demo authorization."""

import base64
import copy
import json
from email import policy
from email.parser import BytesParser
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from fullfill.adapters.orders.square import SquareOrders
from fullfill.main import create_app
from PIL import Image

ACCESS = "demo-code-for-tests-at-least-32-characters"
HEADERS = {"Authorization": "Bearer " + ACCESS}
EDIT_HEADERS = {**HEADERS, "Idempotency-Key": "edit-1"}


def photo(color="orange"):
    output = BytesIO()
    Image.new("RGB", (80, 60), color).save(output, format="PNG")
    return {"data_base64": base64.b64encode(output.getvalue()).decode()}


class SquareCatalog:
    def __init__(self):
        self.objects = []
        self.orders = {}
        self.submissions = []
        self.fail_after_order = False
        self.images = {}
        self.image_uploads = []
        self.fail_after_image = False
        self.fail_after_menu = False
        self.race_menu_save = False

    def __call__(self, request):
        if request.url.path == "/v2/catalog/list":
            return httpx.Response(200, json={"objects": self.objects})
        if request.url.path == "/v2/catalog/images":
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: "
                + request.headers["content-type"].encode()
                + b"\r\n\r\n"
                + request.content
            )
            parts = {
                part.get_param("name", header="content-disposition"): part
                for part in message.iter_parts()
            }
            body = json.loads(parts["request"].get_payload(decode=True))
            data = parts["file"].get_payload(decode=True)
            assert "object_id" not in body  # Never attach before the version-checked save.
            assert parts["file"].get_content_type() in ("image/jpeg", "image/png")
            key = body["idempotency_key"]
            self.image_uploads.append((key, data))
            if key not in self.images:
                image_id = f"image-{len(self.images)}"
                self.images[key] = {
                    "type": "IMAGE",
                    "id": image_id,
                    "image_data": {"url": f"https://images.example.com/{image_id}.png"},
                }
            if self.fail_after_image:
                self.fail_after_image = False
                raise httpx.ReadTimeout("lost image response", request=request)
            return httpx.Response(200, json={"image": self.images[key]})
        body = json.loads(request.content)
        if request.url.path == "/v2/catalog/batch-retrieve":
            return httpx.Response(
                200,
                json={
                    "objects": [
                        image for image in self.images.values() if image["id"] in body["object_ids"]
                    ]
                },
            )
        if request.url.path == "/v2/catalog/object":
            obj = copy.deepcopy(body["object"])
            existing = next((item for item in self.objects if item["id"] == obj["id"]), None)
            if existing:
                if self.race_menu_save:
                    self.race_menu_save = False
                    existing["version"] += 1
                if obj["version"] != existing["version"]:
                    return httpx.Response(400, json={"errors": [{"code": "VERSION_MISMATCH"}]})
                obj["version"] += 1
                self.objects.remove(existing)
            else:
                assert obj["present_at_all_locations"] is False
                assert obj["present_at_location_ids"] == ["our-location"]
                variation = obj["item_data"]["variations"][0]
                assert variation["present_at_all_locations"] is False
                assert variation["present_at_location_ids"] == ["our-location"]
                obj["id"] = f"catalog-{len(self.objects)}"
                obj["version"] = 1
                obj["item_data"]["variations"][0]["id"] = "variation-" + obj["id"]
            self.objects.append(obj)
            if self.fail_after_menu:
                self.fail_after_menu = False
                raise httpx.ReadTimeout("lost menu response", request=request)
            return httpx.Response(200, json={"catalog_object": obj})
        if request.url.path == "/v2/orders/search":
            return httpx.Response(200, json={"orders": list(self.orders.values())})
        assert request.url.path == "/v2/orders"
        key = body["idempotency_key"]
        self.submissions.append(copy.deepcopy(body))
        if key in self.orders:
            assert self.orders[key]["line_items"] == body["order"]["line_items"]
        else:
            self.orders[key] = {"id": "order-" + key, "version": 1, **body["order"]}
        if self.fail_after_order:
            self.fail_after_order = False
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"order": self.orders[key]})


def client_for(square):
    return TestClient(
        create_app(
            SquareOrders(
                "private-square-token",
                "our-location",
                transport=httpx.MockTransport(square),
                catalog=True,
            )
        )
    )


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS)
    monkeypatch.setenv("FULLFILL_WEB_ORIGINS", "https://kitchen.example.com")


def edit(name="Fries", **changes):
    return {
        "item_id": "fries",
        "name": name,
        "price_cents": 400,
        "available": True,
        "archived": False,
        "version": 0,
        **changes,
    }


def add_item(client):
    response = client.post("/v1/menu/items", json=edit(photo=photo()), headers=EDIT_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def prepare(client, snapshot, key="checkout"):
    response = client.post(
        "/v1/orders/prepare",
        json={
            "items": [{"item_id": "fries", "quantity": 2}],
            "menu_revision": snapshot["revision"],
        },
        headers={**HEADERS, "Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_edits_persist_across_api_instances_and_old_orders_keep_their_details():
    square = SquareCatalog()
    with client_for(square) as kitchen:
        initial = add_item(kitchen)
    with client_for(square) as ordering:
        assert ordering.get("/v1/menu/current", headers=HEADERS).json() == initial
        prepared = prepare(ordering, initial)
        created = ordering.post(
            "/v1/orders", json=prepared, headers={**HEADERS, "Idempotency-Key": "checkout"}
        )
        assert created.status_code == 201
        assert created.json()["lines"][0]["item_id"] == "fries"
    with client_for(square) as kitchen:
        response = kitchen.post(
            "/v1/menu/items",
            json=edit("Large fries", price_cents=500, version=1),
            headers={**EDIT_HEADERS, "Idempotency-Key": "edit-2"},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["revision"] != initial["revision"]
    with client_for(square) as ordering:
        assert ordering.get("/v1/menu/current", headers=HEADERS).json() == updated
    assert square.orders["checkout"]["line_items"][0]["name"] == "Fries"
    assert square.orders["checkout"]["line_items"][0]["base_price_money"]["amount"] == 400


def test_stale_basket_requires_review_and_sold_out_or_archived_items_cannot_checkout():
    square = SquareCatalog()
    with client_for(square) as client:
        initial = add_item(client)
        for version, changes in (
            (1, {"available": False}),
            (2, {"available": True, "archived": True}),
        ):
            latest = client.post(
                "/v1/menu/items",
                json=edit(version=version, **changes),
                headers={**EDIT_HEADERS, "Idempotency-Key": f"edit-{version + 1}"},
            ).json()
            for revision, status in ((initial["revision"], 409), (latest["revision"], 422)):
                response = client.post(
                    "/v1/orders/prepare",
                    json={
                        "items": [{"item_id": "fries", "quantity": 1}],
                        "menu_revision": revision,
                    },
                    headers={**HEADERS, "Idempotency-Key": "checkout"},
                )
                assert response.status_code == status
    assert not square.orders


def test_timeout_retry_after_price_change_sends_identical_square_payload():
    square = SquareCatalog()
    with client_for(square) as client:
        prepared = prepare(client, add_item(client))
        square.fail_after_order = True
        assert (
            client.post(
                "/v1/orders", json=prepared, headers={**HEADERS, "Idempotency-Key": "checkout"}
            ).status_code
            == 503
        )
        assert (
            client.post(
                "/v1/menu/items",
                json=edit("Changed fries", price_cents=900, available=False, version=1),
                headers={**EDIT_HEADERS, "Idempotency-Key": "edit-2"},
            ).status_code
            == 200
        )
    with client_for(square) as new_instance:
        retried = new_instance.post(
            "/v1/orders", json=prepared, headers={**HEADERS, "Idempotency-Key": "checkout"}
        )
        assert retried.status_code == 201
        assert retried.json()["lines"][0]["name"] == "Fries"
    assert square.submissions[0] == square.submissions[1]
    assert len(square.orders) == 1


def test_menu_uses_demo_session_and_does_not_touch_unrelated_catalog_items():
    square = SquareCatalog()
    unrelated = {
        "id": "unrelated",
        "type": "ITEM",
        "item_data": {"name": "Existing POS item", "variations": []},
    }
    square.objects.append(copy.deepcopy(unrelated))
    with client_for(square) as client:
        assert (
            client.post(
                "/v1/menu/items", json=edit(), headers={"Idempotency-Key": "no-access"}
            ).status_code
            == 401
        )
        assert client.get("/v1/menu/manage").status_code == 401
        assert client.get("/v1/menu/manage", headers=HEADERS).status_code == 200
        assert client.get("/v1/menu/current", headers=HEADERS).json()["items"] == []
        add_item(client)
    assert square.objects[0] == unrelated


def test_concurrent_item_edit_is_rejected_and_identical_retry_is_safe():
    square = SquareCatalog()
    with client_for(square) as client:
        add_item(client)
        assert client.post("/v1/menu/items", json=edit(), headers=EDIT_HEADERS).status_code == 200
        assert len(square.objects) == 1
        changed = client.post(
            "/v1/menu/items",
            json=edit(price_cents=500, version=1),
            headers={**EDIT_HEADERS, "Idempotency-Key": "edit-2"},
        )
        assert changed.status_code == 200
        response = client.post(
            "/v1/menu/items",
            json=edit(price_cents=600, version=1),
            headers={**EDIT_HEADERS, "Idempotency-Key": "edit-3"},
        )
        assert response.status_code == 409
        assert (
            client.get("/v1/menu/current", headers=HEADERS).json()["items"][0]["price_cents"] == 500
        )


@pytest.mark.parametrize("tampering", ["signature", "items", "key"])
def test_checkout_cannot_change_signed_prices_items_or_identity(tampering):
    square = SquareCatalog()
    with client_for(square) as client:
        prepared = prepare(client, add_item(client))
        key = "checkout"
        if tampering == "signature":
            prepared["quote"] = "tampered." + prepared["quote"].split(".")[-1]
        elif tampering == "items":
            prepared["items"][0]["quantity"] = 20
        else:
            key = "another-checkout"
        response = client.post(
            "/v1/orders", json=prepared, headers={**HEADERS, "Idempotency-Key": key}
        )
        assert response.status_code == 422
    assert not square.orders


def test_menu_save_headers_are_allowed_in_browser_preflight():
    with client_for(SquareCatalog()) as client:
        response = client.options(
            "/v1/menu/items",
            headers={
                "Origin": "https://kitchen.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
            },
        )
        assert response.status_code == 200


def test_new_items_require_photo_but_existing_legacy_items_can_still_be_edited():
    square = SquareCatalog()
    with client_for(square) as client:
        missing = client.post("/v1/menu/items", json=edit(), headers=EDIT_HEADERS)
        assert missing.status_code == 422
        assert not square.objects and not square.image_uploads
        add_item(client)
        del square.objects[0]["item_data"]["image_ids"]
        changed = client.post(
            "/v1/menu/items", json=edit(price_cents=650, version=1), headers=EDIT_HEADERS
        )
        assert changed.status_code == 200
        assert changed.json()["items"][0]["photo_url"] is None
        assert len(square.image_uploads) == 1


def test_photo_and_price_replacement_persist_and_delete_restore_preserves_photo():
    square = SquareCatalog()
    with client_for(square) as client:
        original = add_item(client)["items"][0]
        assert original["photo_url"].endswith("image-0.png")
        replacement = client.post(
            "/v1/menu/items",
            json=edit("Fries large", price_cents=700, version=1, photo=photo("green")),
            headers={**HEADERS, "Idempotency-Key": "replace"},
        )
        assert replacement.status_code == 200
        changed = replacement.json()["items"][0]
        assert changed["photo_id"] != original["photo_id"]
        assert changed["photo_url"].endswith("image-1.png")
        assert changed["price_cents"] == 700
    with client_for(square) as other_screen:
        assert other_screen.get("/v1/menu/manage", headers=HEADERS).json()["items"][0] == changed
        for version, archived in [(2, True), (3, False)]:
            response = other_screen.post(
                "/v1/menu/items",
                json=edit("Fries large", price_cents=700, version=version, archived=archived),
                headers={**HEADERS, "Idempotency-Key": f"archive-{version}"},
            )
            assert response.status_code == 200
            item = response.json()["items"][0]
            assert item["archived"] is archived
            assert item["photo_id"] == changed["photo_id"]
            assert item["photo_url"] == changed["photo_url"]
            assert len(other_screen.get("/v1/menu", headers=HEADERS).json()) == (
                0 if archived else 1
            )
    assert len(square.image_uploads) == 2


@pytest.mark.parametrize("failure", ["fail_after_image", "fail_after_menu"])
def test_retry_after_photo_or_item_response_is_lost_does_not_duplicate(failure):
    square = SquareCatalog()
    setattr(square, failure, True)
    body = edit(photo=photo())
    with client_for(square) as client:
        assert client.post("/v1/menu/items", json=body, headers=EDIT_HEADERS).status_code == 503
    with client_for(square) as restarted:
        retried = restarted.post("/v1/menu/items", json=body, headers=EDIT_HEADERS)
        assert retried.status_code == 200
        assert retried.json()["items"][0]["photo_url"].endswith("image-0.png")
    assert len(square.objects) == len(square.images) == 1
    assert all(upload == square.image_uploads[0] for upload in square.image_uploads)


def test_stale_photo_save_and_square_version_conflict_keep_current_photo():
    square = SquareCatalog()
    with client_for(square) as client:
        original = add_item(client)["items"][0]
        square.race_menu_save = True
        body = edit(version=1, photo=photo("green"))
        response = client.post(
            "/v1/menu/items", json=body, headers={**HEADERS, "Idempotency-Key": "race"}
        )
        assert response.status_code == 409
        current = client.get("/v1/menu/current", headers=HEADERS).json()["items"][0]
        assert current["photo_id"] == original["photo_id"]
        assert current["version"] == 2
        assert len(square.image_uploads) == 2
        stale = client.post(
            "/v1/menu/items", json=body, headers={**HEADERS, "Idempotency-Key": "stale"}
        )
        assert stale.status_code == 409
        assert len(square.image_uploads) == 2  # Reject before uploading a stale edit.


@pytest.mark.parametrize(
    "encoded",
    [
        "not base64!",
        base64.b64encode(b"<svg></svg>").decode(),
        photo()["data_base64"][:60],
        "A" * 2_000_004,
    ],
)
def test_invalid_photos_are_rejected_before_calling_square(encoded):
    square = SquareCatalog()
    with client_for(square) as client:
        response = client.post(
            "/v1/menu/items", json=edit(photo={"data_base64": encoded}), headers=EDIT_HEADERS
        )
        assert response.status_code == 422
    assert not square.objects and not square.image_uploads
