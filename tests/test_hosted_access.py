"""Hosted order data requires a demo code, including on browser cross-origin calls."""

import httpx
import pytest
from fastapi.testclient import TestClient
from fullfill.adapters.orders.square import SquareOrders
from fullfill.main import create_app

ACCESS_CODE = "test-only-demo-access-code-with-entropy"
KITCHEN_CODE = "test-only-kitchen-code-with-different-entropy"
ORDER_SITE = "https://orders.example.com"
KITCHEN_SITE = "https://kitchen.example.com"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("FULLFILL_ACCESS_KEY", raising=False)
    monkeypatch.delenv("FULLFILL_KITCHEN_KEY", raising=False)
    monkeypatch.setenv("FULLFILL_WEB_ORIGINS", f"{ORDER_SITE},{KITCHEN_SITE}")


def test_local_demo_still_works_without_a_code():
    with TestClient(create_app()) as client:
        assert client.get("/v1/session").json() == {
            "required": False,
            "authenticated": True,
            "role": "kitchen",
        }
        assert client.get("/v1/menu").status_code == 200


@pytest.mark.parametrize("key", ["", "too-short"])
def test_hosted_api_fails_closed_when_access_is_not_configured(monkeypatch, key):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", key)
    with TestClient(create_app()) as client:
        for path in ("/v1/session", "/v1/menu", "/v1/stations/main"):
            response = client.get(path, headers={"Origin": ORDER_SITE})
            assert response.status_code == 503
            assert response.headers["Access-Control-Allow-Origin"] == ORDER_SITE
            assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic " + ACCESS_CODE])
def test_unauthorized_requests_never_reach_square(monkeypatch, authorization):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS_CODE)
    monkeypatch.setenv("FULLFILL_KITCHEN_KEY", KITCHEN_CODE)

    def forbidden_square_call(_request):
        pytest.fail("An unauthorized request reached Square")

    source = SquareOrders(
        "private-token", "location", transport=httpx.MockTransport(forbidden_square_call)
    )
    with TestClient(create_app(source)) as client:
        headers = {"Authorization": authorization, "Origin": ORDER_SITE, "Idempotency-Key": "test"}
        assert client.get("/v1/session", headers=headers).json() == {
            "required": True,
            "authenticated": False,
            "role": None,
        }
        for path in ("/v1/orders", "/v1/orders/123", "/v1/stations/main", "/v1/menu"):
            response = client.get(path, headers=headers)
            assert response.status_code == 401
            assert response.headers["Access-Control-Allow-Origin"] == ORDER_SITE
        response = client.post(
            "/v1/orders", json={"items": [{"item_id": "fries", "quantity": 1}]}, headers=headers
        )
        assert response.status_code == 401
        assert ACCESS_CODE not in response.text
        response = client.post(
            "/v1/orders/123/status",
            json={"status": "fulfilled", "expected_revision": 1},
            headers=headers,
        )
        assert response.status_code == 401


def test_both_sites_can_authenticate_and_invalid_origins_are_not_allowed(monkeypatch):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS_CODE)
    monkeypatch.setenv("FULLFILL_KITCHEN_KEY", KITCHEN_CODE)
    with TestClient(create_app()) as client:
        for origin in (ORDER_SITE, KITCHEN_SITE):
            preflight = client.options(
                "/v1/orders",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["Access-Control-Allow-Origin"] == origin
            headers = {"Authorization": f"Bearer {ACCESS_CODE}", "Origin": origin}
            assert client.get("/v1/session", headers=headers).json()["authenticated"] is True
            assert client.get("/v1/menu", headers=headers).status_code == 200
        response = client.options(
            "/v1/orders",
            headers={
                "Origin": "https://untrusted.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 400
        assert "Access-Control-Allow-Origin" not in response.headers


def test_rotating_access_code_invalidates_old_code(monkeypatch):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS_CODE)
    monkeypatch.setenv("FULLFILL_KITCHEN_KEY", KITCHEN_CODE)
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {ACCESS_CODE}"}
        assert client.get("/v1/menu", headers=headers).status_code == 200
        monkeypatch.setenv("FULLFILL_ACCESS_KEY", "a-new-test-code-that-is-at-least-32-characters")
        assert client.get("/v1/menu", headers=headers).status_code == 401


def test_ordering_code_cannot_access_kitchen_even_from_kitchen_origin(monkeypatch):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS_CODE)
    monkeypatch.setenv("FULLFILL_KITCHEN_KEY", KITCHEN_CODE)

    def forbidden(_request):
        pytest.fail("Denied request reached Square")

    source = SquareOrders("token", "location", transport=httpx.MockTransport(forbidden))
    with TestClient(create_app(source)) as client:
        headers = {"Authorization": f"Bearer {ACCESS_CODE}", "Origin": KITCHEN_SITE}
        assert client.get("/v1/session?scope=kitchen", headers=headers).json() == {
            "required": True,
            "authenticated": False,
            "role": "order",
        }
        for method, path in [
            ("GET", "/v1/stations/main"),
            ("GET", "/v1/orders"),
            ("GET", "/v1/orders/123"),
            ("POST", "/v1/orders/123/status"),
            ("POST", "/v1/orders/123/claim"),
            ("GET", "/v1/menu/manage"),
            ("POST", "/v1/menu/items"),
            ("GET", "/v1/checks/camera/config"),
            ("POST", "/v1/checks/camera"),
            ("POST", "/v1/checks/camera/confirm"),
            ("POST", "/v1/stations/main/refresh"),
        ]:
            assert client.request(method, path, headers=headers).status_code == 403


def test_kitchen_code_has_staff_access_and_ordering_code_can_checkout(monkeypatch):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS_CODE)
    monkeypatch.setenv("FULLFILL_KITCHEN_KEY", KITCHEN_CODE)
    source = SquareOrders(
        "token",
        "location",
        transport=httpx.MockTransport(lambda _request: pytest.fail("Unexpected Square call")),
    )
    with TestClient(create_app(source)) as client:
        staff = {"Authorization": f"Bearer {KITCHEN_CODE}"}
        for scope in ("kitchen", "order"):
            assert client.get(f"/v1/session?scope={scope}", headers=staff).json() == {
                "required": True,
                "authenticated": True,
                "role": "kitchen",
            }
        assert client.get("/v1/checks/camera/config", headers=staff).status_code == 200
        for path in ("/v1/orders", "/v1/orders/prepare"):
            # Validation is after authorization. No provider calls are needed here.
            response = client.post(
                path, json={}, headers={"Authorization": f"Bearer {ACCESS_CODE}"}
            )
            assert response.status_code == 422


@pytest.mark.parametrize("kitchen", ["", "short", ACCESS_CODE])
def test_missing_weak_or_shared_kitchen_secret_fails_closed(monkeypatch, kitchen):
    monkeypatch.setenv("FULLFILL_ACCESS_KEY", ACCESS_CODE)
    monkeypatch.setenv("FULLFILL_KITCHEN_KEY", kitchen)
    with TestClient(create_app()) as client:
        assert client.get("/v1/session").status_code == 503
