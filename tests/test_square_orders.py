"""Order ingress tests use recorded-shaped Square responses, never live credentials."""

import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from fullfill.adapters.orders.claims import CLAIM_KEY, claim_value
from fullfill.adapters.orders.square import SquareOrders
from fullfill.main import create_app


def square_order(order_id="square-order-1", **changes):
    return {
        "id": order_id,
        "version": 3,
        "location_id": "test-location",
        "state": "OPEN",
        "metadata": {CLAIM_KEY: claim_value("worker")},
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


def with_status(order, status):
    source = SquareOrders("test-token", "test-location")
    order["metadata"] = {
        **order.get("metadata", {}),
        "fullfill_queue_status": status,
        "fullfill_status_fingerprint": source._ticket_fingerprint(order),
    }
    return order


class QueueStore:
    def __init__(self, orders):
        self.orders = orders
        self.writes = []
        self.before_write = None
        self.lose_response = False

    def __call__(self, request):
        if request.url.path == "/v2/orders/search":
            body = json.loads(request.content)
            assert body["query"]["sort"] == {"sort_field": "CREATED_AT", "sort_order": "ASC"}
            return httpx.Response(200, json={"orders": self.orders})
        order = next(order for order in self.orders if request.url.path.endswith("/" + order["id"]))
        if request.method == "GET":
            return httpx.Response(200, json={"order": order})
        assert request.method == "PUT"
        body = json.loads(request.content)
        self.writes.append(body)
        if self.before_write:
            callback, self.before_write = self.before_write, None
            callback(order)
        if body["order"]["version"] != order["version"]:
            return httpx.Response(400, json={"errors": [{"code": "VERSION_MISMATCH"}]})
        order["metadata"] = body["order"]["metadata"]
        order["version"] += 1
        if self.lose_response:
            self.lose_response = False
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"order": order})


def status_request(client, order_id, status, version=3, key="status-attempt"):
    return client.post(
        f"/v1/orders/{order_id}/status",
        json={"worker_id": "worker", "status": status, "expected_revision": version},
        headers={"Idempotency-Key": key},
    )


@pytest.mark.parametrize("count", [10, 11, 16])
def test_soft_cap_always_keeps_unfulfilled_and_orange_orders(count):
    orders = [square_order(f"order-{number}") for number in range(count)]
    with_status(orders[0], "unsure")
    store = QueueStore(orders)
    with client_for(store) as kitchen:
        response = kitchen.post("/v1/stations/main/refresh")
        assert response.status_code == 200, response.text
        states = response.json()["orders"]
        assert len(states) == count
        assert states[0]["disposition"] == "needs_review"
        assert states[-1]["order"]["order_id"] == f"order-{count - 1}"
    assert not store.writes


@pytest.mark.parametrize("count,removed", [(10, 0), (11, 1), (15, 5)])
def test_overflow_removes_only_oldest_fulfilled_and_persists_across_screens(count, removed):
    orders = [square_order(f"order-{number}") for number in range(count)]
    # Old unresolved work must survive even when completed tickets are newer.
    with_status(orders[0], "unsure")
    for order in orders[2:]:
        order["metadata"] = {"existing": "keep-me"}
        with_status(order, "fulfilled")
    store = QueueStore(orders)
    expected = [order["id"] for order in orders[:2] + orders[2 + removed :]]
    with client_for(store) as kitchen:
        response = kitchen.post("/v1/stations/main/refresh")
        assert response.status_code == 200, response.text
        assert [state["order"]["order_id"] for state in response.json()["orders"]] == expected
    with client_for(store) as other_kitchen:
        assert other_kitchen.get("/v1/stations/main").json() == response.json()
        assert other_kitchen.get("/v1/orders/order-2").status_code == 200
    assert len(store.writes) == removed
    assert all(order["state"] == "OPEN" for order in orders)
    assert all(order["metadata"]["existing"] == "keep-me" for order in orders[2:])


def test_more_than_ten_unresolved_tickets_remain_after_all_green_tickets_are_removed():
    orders = [square_order(f"order-{number}") for number in range(15)]
    with_status(orders[0], "fulfilled")
    with_status(orders[1], "unsure")
    with_status(orders[-1], "fulfilled")
    store = QueueStore(orders)
    with client_for(store) as kitchen:
        states = kitchen.post("/v1/stations/main/refresh").json()["orders"]
    assert len(states) == 13
    assert len(store.writes) == 2
    assert all(state["disposition"] != "overridden" for state in states)


def test_recent_fulfillment_survives_cleanup_for_undo_then_expires(monkeypatch):
    now = 1000
    monkeypatch.setattr("fullfill.adapters.orders.square.time.time", lambda: now)
    orders = [square_order(f"order-{number}") for number in range(11)]
    store = QueueStore(orders)
    with client_for(store) as kitchen:
        assert status_request(kitchen, "order-0", "fulfilled").status_code == 200
        assert len(kitchen.post("/v1/stations/main/refresh").json()["orders"]) == 11
        now += 119
        assert len(kitchen.post("/v1/stations/main/refresh").json()["orders"]) == 11
        now += 2
        states = kitchen.post("/v1/stations/main/refresh").json()["orders"]
        assert len(states) == 10
        assert all(state["order"]["order_id"] != "order-0" for state in states)


@pytest.mark.parametrize("change", ["unfulfilled", "unsure", "items", "archived"])
def test_cleanup_rechecks_after_conflict_and_never_removes_reopened_or_changed_work(change):
    orders = [square_order(f"order-{number}") for number in range(11)]
    with_status(orders[0], "fulfilled")
    store = QueueStore(orders)

    def concurrent_edit(order):
        order["version"] += 1
        if change == "archived":
            order["metadata"]["fullfill_queue_archived"] = "true"
        elif change == "items":
            order["line_items"][0]["quantity"] = "3"
        else:
            with_status(order, change)

    store.before_write = concurrent_edit
    with client_for(store) as kitchen:
        response = kitchen.post("/v1/stations/main/refresh")
    assert response.status_code == 200, response.text
    states = response.json()["orders"]
    assert len(store.writes) == 1
    assert len(states) == (10 if change == "archived" else 11)
    if change != "archived":
        assert states[0]["order"]["order_id"] == "order-0"
        assert states[0]["disposition"] == ("needs_review" if change == "unsure" else "pending")


@pytest.mark.parametrize(
    "status,disposition",
    [("fulfilled", "overridden"), ("unsure", "needs_review"), ("unfulfilled", "pending")],
)
def test_status_is_shared_between_independent_screens_and_retries_are_idempotent(
    status, disposition
):
    order = square_order(metadata={"existing": "keep-me", CLAIM_KEY: claim_value("worker")})
    store = QueueStore([order])
    with client_for(store) as kitchen:
        response = status_request(kitchen, order["id"], status)
        assert response.status_code == 200, response.text
        assert status_request(kitchen, order["id"], status).json() == response.json()
    with client_for(store) as other:
        state = other.get("/v1/stations/main").json()["orders"][0]
        assert state == response.json()
        assert state["disposition"] == disposition
        assert state["current_check"] is None
        assert state["order"]["revision"] == 4
    assert len(store.writes) == 1
    assert order["metadata"]["existing"] == "keep-me"
    assert order["state"] == "OPEN"


def test_lost_status_response_is_recovered_without_duplicate_writes():
    order = square_order()
    store = QueueStore([order])
    store.lose_response = True
    with client_for(store) as kitchen:
        assert status_request(kitchen, order["id"], "fulfilled").status_code == 503
        retry = status_request(kitchen, order["id"], "fulfilled")
    assert retry.status_code == 200
    assert retry.json()["disposition"] == "overridden"
    assert len(store.writes) == 1


@pytest.mark.parametrize("during_write", [False, True])
def test_conflicting_status_edits_require_refresh_instead_of_overwriting_other_screen(during_write):
    order = square_order()
    store = QueueStore([order])
    if during_write:

        def other_screen(order):
            with_status(order, "unsure")
            order["version"] += 1

        store.before_write = other_screen
    else:
        with client_for(store) as first:
            assert status_request(first, order["id"], "unsure").status_code == 200
    with client_for(store) as second:
        response = status_request(second, order["id"], "fulfilled", key="other-screen")
    assert response.status_code == 409
    assert len(store.writes) == 1
    assert order["metadata"]["fullfill_queue_status"] == "unsure"


def test_order_edit_invalidates_fulfilled_status_and_protects_ticket_from_cleanup():
    orders = [square_order(f"order-{number}") for number in range(11)]
    store = QueueStore(orders)
    with client_for(store) as kitchen:
        assert status_request(kitchen, "order-0", "fulfilled").status_code == 200
        orders[0]["line_items"][0]["quantity"] = "3"
        orders[0]["version"] += 1
        states = kitchen.post("/v1/stations/main/refresh").json()["orders"]
    assert len(states) == 11
    assert states[0]["disposition"] == "pending"
    assert states[0]["order"]["lines"][0]["quantity"] == 3
    assert len(store.writes) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"status": "unknown", "expected_revision": 3},
        {"status": "fulfilled", "expected_revision": 0},
        {"status": "fulfilled", "expected_revision": True},
    ],
)
def test_invalid_status_edits_never_reach_square(body):
    with client_for(lambda _: pytest.fail("Validation must run before Square")) as client:
        response = client.post(
            "/v1/orders/test/status", json=body, headers={"Idempotency-Key": "test"}
        )
    assert response.status_code == 422


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
