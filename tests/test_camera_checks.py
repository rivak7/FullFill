"""Camera integration with fake Square and fake vision; never consumes API credit."""

import asyncio
import base64
import copy
import hashlib
import json
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from fullfill.adapters.orders.camera_checks import CHECK_KEY, RESULT_KEYS
from fullfill.adapters.orders.square import SquareOrders
from fullfill.adapters.vision.perceptron import VisionProviderError
from fullfill.application.order_source import MenuEntry, MenuSnapshot
from fullfill.main import create_app
from fullfill_contracts.vision import ImageInput, Observations, TargetObservation, UnexpectedItem
from PIL import Image


def photo(color="white"):
    output = BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format="JPEG")
    return {"data_base64": base64.b64encode(output.getvalue()).decode()}


class Square:
    def __init__(self):
        self.order = {
            "id": "ticket",
            "location_id": "location",
            "version": 3,
            "state": "OPEN",
            "line_items": [
                {
                    "uid": "line",
                    "name": "Fries",
                    "quantity": "2",
                    "metadata": {
                        "fullfill_item_id": "fries",
                        "fullfill_verification_mode": "visible_item",
                    },
                }
            ],
        }
        self.lose_finish_response = False

    def request(self, request):
        if request.method == "PUT":
            body = json.loads(request.content)
            if body["order"]["version"] != self.order["version"]:
                return httpx.Response(409, json={"errors": [{"code": "VERSION_MISMATCH"}]})
            self.order.update(body["order"])
            self.order["version"] += 1
            metadata = self.order["metadata"]
            assert len(metadata) <= 10
            assert all(1 <= len(value) <= 255 for value in metadata.values())
            if self.lose_finish_response and body["idempotency_key"].startswith("camera-finish-"):
                self.lose_finish_response = False
                raise httpx.ReadTimeout("Lost response")
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"orders": [copy.deepcopy(self.order)]})
        return httpx.Response(200, json={"order": copy.deepcopy(self.order)})

    def app(self, provider=None):
        app = create_app(
            SquareOrders("token", "location", transport=httpx.MockTransport(self.request))
        )
        if provider is not None:
            app.state.vision_provider = provider
        return app


class Vision:
    def __init__(self, count=2, status="present", unexpected=False):
        self.calls = []
        self.count = count
        self.status = status
        self.unexpected = unexpected
        self.before_result = None
        self.scene_uncertainty = None
        self.reason = None

    async def inspect(self, request):
        self.calls.append(request)
        if self.before_result:
            self.before_result()
        return Observations(
            capture_id=request.capture_id,
            targets=[
                TargetObservation(
                    target_id=target.target_id,
                    status=self.status,
                    observed_quantity=self.count,
                    reason=self.reason,
                )
                for target in request.targets
            ],
            unexpected_items=[UnexpectedItem(name="Drink")] if self.unexpected else [],
            scene_uncertainty=self.scene_uncertainty,
        )


def send(client, key="attempt", revision=3, image=None):
    return client.post(
        "/v1/checks/camera",
        headers={"Idempotency-Key": key},
        json={"order_id": "ticket", "expected_revision": revision, "photo": image or photo()},
    )


@pytest.fixture(autouse=True)
def saved_reference_photos(monkeypatch):
    async def menu(source):
        order = await source.get_order("ticket")
        return MenuSnapshot(
            revision="menu",
            items=[
                MenuEntry(
                    item_id=line.item_id,
                    name=line.name,
                    description="",
                    price_cents=400,
                    photo_url=f"https://items-images-production.s3.amazonaws.com/{line.item_id}.jpg",
                )
                for line in order.lines
            ],
        )

    async def reference(_url):
        return ImageInput(b"fake-reference", "image/jpeg")

    monkeypatch.setattr(SquareOrders, "menu", menu)
    monkeypatch.setattr("fullfill.http.checks.reference_image", reference)


@pytest.mark.parametrize(
    "count,status,unexpected,verdict",
    [
        (2, "present", False, "pass"),
        (1, "present", False, "fail"),
        (None, "unsure", False, "unsure"),
        (2, "present", True, "unsure"),
    ],
)
def test_check_is_shared_across_instances_and_retry_never_pays_twice(
    count, status, unexpected, verdict
):
    square, vision = Square(), Vision(count, status, unexpected)
    with TestClient(square.app(vision)) as client:
        assert client.get("/v1/checks/camera/config").json()["configured"] is True
        result = send(client)
        assert result.status_code == 200, result.text
        assert result.json()["current_check"]["verdict"] == verdict
        assert len(vision.calls) == 1
        assert send(client).json() == result.json()
        assert len(vision.calls) == 1
    with TestClient(square.app()) as other:
        state = other.get("/v1/stations/main").json()["orders"][0]
    assert state == result.json()
    assert "data_base64" not in json.dumps(square.order)


def test_revision_change_before_capture_never_calls_vision():
    square, vision = Square(), Vision()
    square.order["version"] += 1
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 409
    assert not vision.calls


def test_manual_decision_during_inference_wins():
    square, vision = Square(), Vision()

    def reopen():
        with TestClient(square.app()) as other:
            result = other.post(
                "/v1/orders/ticket/status",
                headers={"Idempotency-Key": "manual"},
                json={"status": "unsure", "expected_revision": square.order["version"]},
            )
            assert result.status_code == 200

    vision.before_result = reopen
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 409
        state = client.get("/v1/stations/main").json()["orders"][0]
    assert state["disposition"] == "needs_review"
    assert state["current_check"] is None
    assert len(vision.calls) == 1


def test_lost_response_is_recovered_without_another_paid_call():
    square, vision = Square(), Vision()
    square.lose_finish_response = True
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 503
        assert send(client).json()["disposition"] == "verified"
    assert len(vision.calls) == 1


def test_failed_provider_never_goes_green_and_does_not_leak_error_or_retry():
    class FailedVision(Vision):
        async def inspect(self, request):
            self.calls.append(request)
            raise VisionProviderError("secret-key and raw response")

    square, vision = Square(), FailedVision()
    with TestClient(square.app(vision)) as client:
        result = send(client)
        assert result.status_code == 502
        assert "secret-key" not in result.text
        state = send(client).json()
        assert state["current_check"]["execution_status"] == "failed"
        assert state["disposition"] == "needs_review"
    assert len(vision.calls) == 1


def test_duplicate_keys_reject_different_images_but_new_checks_need_no_cooldown():
    square, vision = Square(), Vision(count=1)
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 200
        assert send(client, image=photo("black")).status_code == 409
        assert send(client, key="new", revision=square.order["version"]).status_code == 200
    assert len(vision.calls) == 2


def test_existing_twenty_attempt_orders_can_keep_checking_after_restart():
    square, vision = Square(), Vision(count=1)
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 200
    record = json.loads(square.order["metadata"][CHECK_KEY])
    record["n"] = 20
    square.order["metadata"][CHECK_KEY] = json.dumps(record)
    with TestClient(square.app(vision)) as other:
        for index in range(25):
            result = send(other, key=f"new-{index}", revision=square.order["version"])
            assert result.status_code == 200, result.text
    assert len(vision.calls) == 26
    assert json.loads(square.order["metadata"][CHECK_KEY])["n"] == 45


def test_missing_references_never_fall_back_to_names_only(monkeypatch):
    async def no_photo(_source):
        return MenuSnapshot(
            revision="menu",
            items=[
                MenuEntry(
                    item_id="fries",
                    name="Fries",
                    description="",
                    price_cents=400,
                )
            ],
        )

    monkeypatch.setattr(SquareOrders, "menu", no_photo)
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        result = send(client)
        assert result.status_code == 422
        assert "reference photo" in result.json()["detail"]
        assert "Fries" in result.json()["detail"]
        assert client.get("/v1/stations/main").json()["orders"][0]["disposition"] == "needs_review"
    assert not vision.calls


def test_unavailable_reference_does_not_call_vision(monkeypatch):
    async def unavailable(_url):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("fullfill.http.checks.reference_image", unavailable)
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 502
    assert not vision.calls


def test_modified_lines_keep_separate_counts_and_require_staff_confirmation():
    square, vision = Square(), Vision(count=1)
    square.order["line_items"] = [
        {
            "uid": "regular",
            "name": "Fries",
            "quantity": "1",
            "metadata": {"fullfill_item_id": "fries"},
        },
        {
            "uid": "custom",
            "name": "Fries",
            "quantity": "1",
            "metadata": {"fullfill_item_id": "fries"},
            "modifiers": [{"name": "No salt"}],
        },
    ]
    with TestClient(square.app(vision)) as client:
        result = send(client)
        assert result.status_code == 200, result.text
        assert result.json()["disposition"] == "needs_review"
        assert "No salt" in result.json()["current_check"]["discrepancies"][0]["message"]
    assert len(vision.calls[0].targets) == 2
    assert {t.name for t in vision.calls[0].targets} == {"Fries", "Fries — No salt"}
    with TestClient(square.app()) as other:
        assert other.get("/v1/stations/main").json()["orders"][0] == result.json()


def test_existing_plain_order_fingerprints_survive_but_modified_approvals_expire():
    square = Square()
    source = SquareOrders("token", "location")

    def legacy_fingerprint():
        lines = [
            line.model_dump(mode="json", exclude={"requires_manual_review"})
            for line in source._snapshot(square.order).lines
        ]
        return hashlib.sha256(json.dumps(lines, sort_keys=True).encode()).hexdigest()

    square.order["metadata"] = {
        "fullfill_queue_status": "fulfilled",
        "fullfill_status_fingerprint": legacy_fingerprint(),
    }
    assert source._order_state(square.order).disposition == "overridden"
    square.order["line_items"][0]["note"] = "No salt"
    square.order["metadata"]["fullfill_status_fingerprint"] = legacy_fingerprint()
    assert source._order_state(square.order).disposition == "pending"


def test_camera_bytes_and_bad_photos_never_leak_into_validation_response():
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        result = send(client, image={"data_base64": "not-a-photo-private-marker"})
    assert result.status_code == 422
    assert "private-marker" not in result.text
    assert not vision.calls


def test_unconfigured_camera_preview_does_not_call_a_provider(monkeypatch):
    monkeypatch.delenv("PERCEPTRON_API_KEY", raising=False)
    with TestClient(Square().app()) as client:
        assert client.get("/v1/checks/camera/config").json()["configured"] is False
        assert send(client).status_code == 503


def test_concurrent_screens_only_reserve_one_paid_call():
    square = Square()

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowVision(Vision):
            async def inspect(self, request):
                entered.set()
                await release.wait()
                return await super().inspect(request)

        vision = SlowVision()
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=square.app(vision)), base_url="http://test"
            ) as first,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=square.app(vision)), base_url="http://test"
            ) as second,
        ):
            body = {"order_id": "ticket", "expected_revision": 3, "photo": photo()}
            pending = asyncio.create_task(
                first.post("/v1/checks/camera", headers={"Idempotency-Key": "one"}, json=body)
            )
            await entered.wait()
            duplicate = await second.post(
                "/v1/checks/camera", headers={"Idempotency-Key": "one"}, json=body
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["current_check"]["execution_status"] == "running"
            body["expected_revision"] = square.order["version"]
            other = await second.post(
                "/v1/checks/camera", headers={"Idempotency-Key": "two"}, json=body
            )
            assert other.status_code == 409
            release.set()
            assert (await pending).status_code == 200
            assert len(vision.calls) == 1

    asyncio.run(scenario())


def test_ticket_edit_invalidates_a_completed_check():
    square = Square()
    with TestClient(square.app(Vision())) as client:
        assert send(client).json()["disposition"] == "verified"
        square.order["line_items"][0]["quantity"] = "3"
        square.order["version"] += 1
        state = client.get("/v1/stations/main").json()["orders"][0]
    assert state["current_check"] is None
    assert state["disposition"] == "pending"


def test_uses_only_saved_references_for_ticket_items(monkeypatch):
    from fullfill.application.order_source import MenuEntry, MenuSnapshot
    from fullfill_contracts.vision import ImageInput

    seen = []

    async def menu(_self):
        return MenuSnapshot(
            revision="menu",
            items=[
                MenuEntry(
                    item_id="fries",
                    name="Fries",
                    description="",
                    price_cents=400,
                    photo_url="https://items-images-production.s3.us-west-2.amazonaws.com/fries.jpg",
                ),
                MenuEntry(
                    item_id="drink",
                    name="Drink",
                    description="",
                    price_cents=300,
                    photo_url="https://items-images-production.s3.us-west-2.amazonaws.com/drink.jpg",
                ),
            ],
        )

    async def reference(url):
        seen.append(url)
        return ImageInput(b"reference", "image/jpeg")

    monkeypatch.setattr(SquareOrders, "menu", menu)
    monkeypatch.setattr("fullfill.http.checks.reference_image", reference)
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 200
    assert len(seen) == 1 and seen[0].endswith("fries.jpg")
    assert vision.calls[0].references[0].item_id == "fries"


def test_twenty_large_counts_fit_square_metadata_limits():
    square, vision = Square(), Vision(count=100000)
    square.order["line_items"] = [
        {
            "uid": f"line-{index}",
            "name": f"Item {index}",
            "quantity": "1",
            "metadata": {"fullfill_item_id": f"item-{index}"},
        }
        for index in range(20)
    ]
    with TestClient(square.app(vision)) as client:
        result = send(client)
    assert result.status_code == 200, result.text
    assert result.json()["current_check"]["verdict"] == "fail"
    assert len(result.json()["current_check"]["discrepancies"]) == 20


def test_short_result_replaces_both_chunks_after_a_long_result(monkeypatch):
    square, vision = Square(), Vision(count=100000)
    square.order["line_items"] = [
        {
            "uid": f"line-{index}",
            "name": f"Item {index}",
            "quantity": "1",
            "metadata": {"fullfill_item_id": f"item-{index}"},
        }
        for index in range(20)
    ]
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 200
        assert len(square.order["metadata"][RESULT_KEYS[1]]) > 1
        record = json.loads(square.order["metadata"][CHECK_KEY])
        monkeypatch.setattr(
            "fullfill.adapters.orders.camera_checks.time.time", lambda: record["t"] + 100
        )
        vision.count = 0
        vision.status = "missing"
        result = send(client, key="shorter", revision=square.order["version"])
    assert result.status_code == 200, result.text
    assert result.json()["current_check"]["execution_status"] == "completed"
    assert result.json()["current_check"]["verdict"] == "fail"
    assert len(square.order["metadata"][RESULT_KEYS[1]]) == 1
    with TestClient(square.app()) as other:
        shared = other.get("/v1/stations/main").json()["orders"][0]
    assert shared == result.json()
    assert len(vision.calls) == 2


def test_scene_uncertainty_and_reason_survive_square_storage():
    square, vision = Square(), Vision()
    vision.scene_uncertainty = "Keep the entire order inside the camera preview."
    with TestClient(square.app(vision)) as client:
        result = send(client)
    assert result.status_code == 200, result.text
    assert result.json()["disposition"] == "needs_review"
    with TestClient(square.app()) as other:
        shared = other.get("/v1/stations/main").json()["orders"][0]
    assert shared == result.json()
    assert shared["current_check"]["discrepancies"][0]["message"] == vision.scene_uncertainty


def test_item_uncertainty_keeps_actionable_reason_and_manual_correction_wins():
    from fullfill.domain.vision_uncertainty import REASONS

    square, vision = Square(), Vision(status="unsure")
    vision.reason = REASONS["label"]
    with TestClient(square.app(vision)) as client:
        result = send(client).json()
        assert REASONS["label"] in result["current_check"]["discrepancies"][0]["message"]
        corrected = client.post(
            "/v1/orders/ticket/status",
            headers={"Idempotency-Key": "staff-confirm"},
            json={"status": "fulfilled", "expected_revision": result["order"]["revision"]},
        )
        assert corrected.json()["disposition"] == "overridden"
        assert corrected.json()["current_check"] is None
    assert len(vision.calls) == 1


def test_maximum_result_preserves_uncertainty_within_square_limits():
    from fullfill.domain.vision_uncertainty import REASONS

    square, vision = Square(), Vision(count=100000, status="unsure", unexpected=True)
    vision.reason = REASONS["identity"]
    vision.scene_uncertainty = '"' * 80
    square.order["line_items"] = [
        {
            "uid": f"line-{index}",
            "name": f"Item {index}",
            "quantity": "1",
            "metadata": {"fullfill_item_id": f"item-{index}"},
        }
        for index in range(20)
    ]
    with TestClient(square.app(vision)) as client:
        result = send(client)
    assert result.status_code == 200, result.text
    assert result.json()["disposition"] == "needs_review"
    assert result.json()["current_check"]["verdict"] == "unsure"
