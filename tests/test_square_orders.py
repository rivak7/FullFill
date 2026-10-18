"""Order ingress tests use recorded-shaped Square responses, never live credentials."""

import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from fullfill.adapters.orders.square import SquareOrders
from fullfill.main import create_app


def square_order(order_id="square-order-1", **changes):
    return {
        "id": order_id,
        "version": 3,
        "location_id": "test-location",
        "state": "OPEN",
        "line_items": [{"uid": "line-1", "name": "Chicken burrito", "quantity": "2"}],
        **changes,
    }


def client_for(handler):
    return TestClient(
        create_app(
            SquareOrders(
                "private-test-token", "test-location", transport=httpx.MockTransport(handler)
            )
        )
    )


def test_order_creation_then_independent_screen_reads_square_and_retry_is_idempotent():
    stored = {}
    calls = []

    def square(request):
        assert request.url.host == "connect.squareupsandbox.com"
        assert request.headers["Authorization"] == "Bearer private-test-token"
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/v2/orders":
            key = body["idempotency_key"]
            if key not in stored:
                stored[key] = square_order(**body["order"])
            return httpx.Response(200, json={"order": stored[key]})
        assert body["location_ids"] == ["test-location"]
        assert body["query"]["filter"]["state_filter"]["states"] == ["OPEN"]
        return httpx.Response(200, json={"orders": list(stored.values())})

    body = {
        "items": [
            {"item_id": "chicken_burrito", "quantity": 2},
            {"item_id": "fries", "quantity": 1},
        ]
    }
    with client_for(square) as ordering:
        created = ordering.post(
            "/v1/orders",
            json=body,
            headers={"Idempotency-Key": "d6c40e0f-6bfc-45d0-a191-550f43c99921"},
        )
        repeated = ordering.post(
            "/v1/orders",
            json=body,
            headers={"Idempotency-Key": "d6c40e0f-6bfc-45d0-a191-550f43c99921"},
        )
    assert created.status_code == 201
    assert repeated.json() == created.json()
    assert len(stored) == 1
    assert calls[0][1]["order"]["line_items"][0]["base_price_money"] == {
        "amount": 1000,
        "currency": "USD",
    }
    assert calls[0][1] == calls[1][1]
    assert len(calls[0][1]["order"]["reference_id"]) <= 40

    # A separate app instance has no local order cache; this models the other screen/backend.
    with client_for(square) as fulfillment:
        snapshot = fulfillment.get("/v1/stations/main")
    assert snapshot.status_code == 200
    assert snapshot.headers["Cache-Control"] == "no-store"
    state = snapshot.json()["orders"][0]
    assert state["order"] == created.json()
    assert state["order"]["lines"][0]["verification_mode"] == "label"
    assert state["current_check"] is None
    assert state["disposition"] == "pending"
    assert "private-test-token" not in snapshot.text


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"item_id": "fries", "quantity": 0}],
        [{"item_id": "fries", "quantity": -1}],
        [{"item_id": "fries", "quantity": 1.5}],
        [{"item_id": "fries", "quantity": True}],
        [{"item_id": "fries", "quantity": 51}],
        [{"item_id": "fries", "quantity": 1, "price_cents": 1}],
        [{"item_id": "unknown", "quantity": 1}],
        [{"item_id": "fries", "quantity": 1}, {"item_id": "fries", "quantity": 2}],
    ],
)
def test_invalid_baskets_never_reach_square(items):
    def square(_request):
        pytest.fail("Validation must finish before any provider request")

    with client_for(square) as client:
        response = client.post(
            "/v1/orders", json={"items": items}, headers={"Idempotency-Key": "attempt"}
        )
    assert response.status_code == 422


def test_creation_requires_idempotency_header():
    with client_for(lambda _request: pytest.fail("Must not submit without a key")) as client:
        response = client.post("/v1/orders", json={"items": [{"item_id": "fries", "quantity": 1}]})
    assert response.status_code == 422


def test_queue_follows_pagination_skips_empty_and_terminal_orders():
    requests = []

    def square(request):
        body = json.loads(request.content)
        requests.append(copy.deepcopy(body))
        if not body.get("cursor"):
            return httpx.Response(
                200,
                json={
                    "orders": [square_order("first"), square_order("empty", line_items=[])],
                    "cursor": "next",
                },
            )
        return httpx.Response(
            200,
            json={"orders": [square_order("second"), square_order("closed", state="COMPLETED")]},
        )

    with client_for(square) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 200
    assert [order["order_id"] for order in response.json()] == ["first", "second"]
    assert requests[0]["query"] == requests[1]["query"]
    assert requests[1]["cursor"] == "next"


def test_thirty_first_order_drops_oldest_ticket_from_all_kitchen_screens():
    orders = [square_order(f"order-{number}") for number in range(30, 0, -1)]

    def square(request):
        if request.method == "GET":
            return httpx.Response(200, json={"order": orders[-1]})
        body = json.loads(request.content)
        assert body["query"]["sort"] == {"sort_field": "CREATED_AT", "sort_order": "DESC"}
        return httpx.Response(200, json={"orders": orders})

    with client_for(square) as kitchen:
        initial = kitchen.get("/v1/orders").json()
        assert len(initial) == 30
        assert initial[-1]["order_id"] == "order-1"
        orders.insert(0, square_order("order-31"))
        updated = kitchen.get("/v1/orders").json()
        assert len(updated) == 30
        assert updated[0]["order_id"] == "order-31"
        assert updated[-1]["order_id"] == "order-2"
        assert kitchen.get("/v1/orders/order-1").status_code == 200
    with client_for(square) as other_kitchen:
        assert other_kitchen.get("/v1/orders").json() == updated


@pytest.mark.parametrize("concurrent", [False, True])
def test_queue_overflow_removal_persists_and_tolerates_another_kitchen_refresh(concurrent):
    orders = [square_order(f"order-{number}") for number in range(31, 0, -1)]
    orders[-1]["metadata"] = {"existing": "keep-me"}
    writes = []

    def square(request):
        if request.url.path == "/v2/orders/search":
            return httpx.Response(200, json={"orders": orders})
        assert request.url.path == "/v2/orders/order-1"
        if request.method == "GET":
            return httpx.Response(200, json={"order": orders[-1]})
        assert request.method == "PUT"
        body = json.loads(request.content)
        writes.append(body)
        orders[-1]["metadata"].update(fullfill_queue_archived="true")
        orders[-1]["version"] += 1
        if concurrent:
            return httpx.Response(400, json={"errors": [{"code": "VERSION_MISMATCH"}]})
        return httpx.Response(200, json={"order": orders[-1]})

    with client_for(square) as kitchen:
        response = kitchen.post("/v1/stations/main/refresh")
        assert response.status_code == 200, response.text
        assert len(response.json()["orders"]) == 30
        assert response.json()["orders"][-1]["order"]["order_id"] == "order-2"
    assert len(writes) == 1
    assert writes[0]["order"] == {
        "location_id": "test-location",
        "version": 3,
        "metadata": {"existing": "keep-me", "fullfill_queue_archived": "true"},
    }
    assert orders[-1]["state"] == "OPEN"
    for order in orders[:-1]:
        order["state"] = "COMPLETED"
    with client_for(square) as second_kitchen:
        assert second_kitchen.post("/v1/stations/main/refresh").json()["orders"] == []
        assert second_kitchen.get("/v1/orders/order-1").status_code == 200
    assert len(writes) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_provider_errors_are_visible_and_never_expose_credentials(status):
    with client_for(
        lambda _: httpx.Response(status, json={"errors": [{"detail": "private-test-token"}]})
    ) as client:
        response = client.get("/v1/stations/main")
    assert response.status_code in (502, 503)
    assert "private-test-token" not in response.text
    assert "detail" in response.json()
    assert "orders" not in response.json()


def test_timeout_is_retryable_without_reporting_an_empty_queue():
    def square(request):
        raise httpx.ReadTimeout("sensitive upstream details", request=request)

    with client_for(square) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 503
    assert "sensitive" not in response.text


@pytest.mark.parametrize("quantity", ["1.5", "0", "-1", "NaN", "invalid"])
def test_fractional_or_invalid_upstream_quantities_are_not_silently_rounded(quantity):
    order = square_order()
    order["line_items"][0]["quantity"] = quantity
    with client_for(lambda _: httpx.Response(200, json={"orders": [order]})) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 502


def test_ticket_preserves_modifiers_and_restricts_location():
    order = square_order()
    order["line_items"][0].update(
        {"variation_name": "Large", "note": "No onions", "modifiers": [{"name": "Extra rice"}]}
    )
    with client_for(lambda _: httpx.Response(200, json={"order": order})) as client:
        response = client.get("/v1/orders/square-order-1")
    assert response.json()["lines"][0]["name"] == "Chicken burrito — Large, No onions, Extra rice"
    with client_for(
        lambda _: httpx.Response(200, json={"order": square_order(location_id="elsewhere")})
    ) as client:
        response = client.get("/v1/orders/square-order-1")
    assert response.status_code == 404


def test_missing_credentials_and_production_configuration_are_explicit(monkeypatch):
    monkeypatch.delenv("SQUARE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SQUARE_LOCATION_ID", raising=False)
    monkeypatch.setenv("SQUARE_ENVIRONMENT", "sandbox")
    with TestClient(create_app()) as client:
        assert client.get("/v1/menu").status_code == 200
        assert client.get("/v1/orders").status_code == 503
    monkeypatch.setenv("SQUARE_ENVIRONMENT", "production")
    monkeypatch.setenv("SQUARE_ACCESS_TOKEN", "private-test-token")
    monkeypatch.setenv("SQUARE_LOCATION_ID", "test-location")
    with TestClient(create_app()) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 503
    assert "requires SQUARE_ENVIRONMENT=sandbox" in response.json()["detail"]


def test_measured_quantity_is_not_misrepresented_as_an_item_count():
    order = square_order()
    order["line_items"][0]["quantity_unit"] = {
        "measurement_unit": {"weight_unit": "IMPERIAL_POUND"}
    }
    with client_for(lambda _: httpx.Response(200, json={"orders": [order]})) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 502


@pytest.mark.parametrize(
    "payload", [{"orders": None}, {"orders": [None]}, {"orders": [], "cursor": {"bad": "cursor"}}]
)
def test_malformed_queue_is_a_visible_provider_error(payload):
    with client_for(lambda _: httpx.Response(200, json=payload)) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 502


def test_repeating_page_cursor_does_not_silently_return_a_partial_queue():
    with client_for(
        lambda _: httpx.Response(200, json={"orders": [square_order()], "cursor": "repeating"})
    ) as client:
        response = client.get("/v1/orders")
    assert response.status_code == 502
