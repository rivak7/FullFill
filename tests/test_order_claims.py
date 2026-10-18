"""Reservations use Square CAS across independent app processes; no live calls."""

import json

import pytest
from fullfill.adapters.orders.claims import CLAIM_KEY, claim_value
from test_square_orders import QueueStore, client_for, square_order, status_request


def claim(client, worker, revision, release=False):
    return client.post(
        "/v1/orders/ticket/claim",
        json={"worker_id": worker, "expected_revision": revision, "release": release},
    )


def test_two_screens_cannot_claim_same_ticket_and_only_owner_can_write():
    store = QueueStore([square_order("ticket", metadata={})])
    with client_for(store) as first, client_for(store) as second:
        owned = claim(first, "a", 3)
        assert owned.status_code == 200
        assert owned.json()["claim"]["worker_id"] == "a"
        assert claim(second, "b", 3).status_code == 409
        assert status_request(second, "ticket", "fulfilled", version=4).status_code == 409
        assert claim(first, "a", 3).json() == owned.json()  # lost-response retry
        assert claim(second, "b", 4, release=True).json() == owned.json()
        assert len(store.writes) == 1
        assert claim(first, "a", 4, release=True).json()["claim"] is None
        assert claim(second, "b", 5).json()["claim"]["worker_id"] == "b"


def test_expired_claim_can_be_reassigned_and_late_release_cannot_clear_it(monkeypatch):
    now = [1000]
    monkeypatch.setattr("fullfill.adapters.orders.claims.time.time", lambda: now[0])
    store = QueueStore([square_order("ticket", metadata={})])
    with client_for(store) as client:
        assert claim(client, "a", 3).status_code == 200
        now[0] += 121
        assert claim(client, "b", 4).status_code == 200
        assert claim(client, "a", 4, release=True).json()["claim"]["worker_id"] == "b"
        now[0] += 61
        renewed = claim(client, "b", 5)
        assert renewed.status_code == 200
        assert renewed.json()["claim"]["expires_at"] == now[0] + 120
        assert claim(client, "b", 5, release=True).status_code == 409
        assert json.loads(store.orders[0]["metadata"][CLAIM_KEY])["id"] == "b"


@pytest.mark.parametrize("change", ["edit", "competing-worker"])
def test_race_during_claim_write_is_rejected(change):
    store = QueueStore([square_order("ticket", metadata={})])

    def race(order):
        order["version"] += 1
        if change == "edit":
            order["line_items"][0]["quantity"] = "3"
        else:
            order["metadata"][CLAIM_KEY] = claim_value("b")

    store.before_write = race
    with client_for(store) as client:
        assert claim(client, "a", 3).status_code == 409
    assert (CLAIM_KEY in store.orders[0]["metadata"]) == (change == "competing-worker")
