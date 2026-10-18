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
from fullfill.adapters.orders.camera_checks import CHECK_KEY
from fullfill.adapters.orders.check_storage import RESULT_KEYS
from fullfill.adapters.orders.claims import CLAIM_KEY, claim_value
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
            "metadata": {CLAIM_KEY: claim_value("worker")},
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
            patch = body["order"].copy()
            for line in patch.pop("line_items", []):
                existing = next(
                    item for item in self.order["line_items"] if item["uid"] == line["uid"]
                )
                existing.setdefault("metadata", {}).update(line["metadata"])
                assert len(existing["metadata"]) <= 10
                assert all(1 <= len(value) <= 255 for value in existing["metadata"].values())
            self.order.update(patch)
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


def send(client, key="attempt", revision=3, image=None, confirm=True, worker="worker"):
    result = client.post(
        "/v1/checks/camera",
        headers={"Idempotency-Key": key},
        json={
            "worker_id": worker,
            "order_id": "ticket",
            "expected_revision": revision,
            "photo": image or photo(),
        },
    )

    if (
        confirm
        and result.status_code == 200
        and result.json()["current_check"]["execution_status"] == "awaiting_confirmation"
    ):
        return confirmation(client, result.json(), worker=worker)
    return result


def confirmation(client, state, unchanged=True, worker="worker"):
    return client.post(
        "/v1/checks/camera/confirm",
        json={
            "order_id": "ticket",
            "check_id": state["current_check"]["check_id"],
            "expected_revision": state["order"]["revision"],
            "worker_id": worker,
            "scene_unchanged": unchanged,
        },
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

    async def reference(_url, revision=0):
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


@pytest.mark.parametrize(
    "status,disposition", [("fulfilled", "overridden"), ("unsure", "needs_review")]
)
def test_manual_decision_during_inference_wins(status, disposition):
    square, vision = Square(), Vision()

    def reopen():
        with TestClient(square.app()) as other:
            result = other.post(
                "/v1/orders/ticket/status",
                headers={"Idempotency-Key": "manual"},
                json={
                    "worker_id": "worker",
                    "status": status,
                    # The screen still has the version from before scan reservation.
                    "expected_revision": 3,
                },
            )
            assert result.status_code == 200

    vision.before_result = reopen
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 409
        state = client.get("/v1/stations/main").json()["orders"][0]
    assert state["disposition"] == disposition
    assert state["current_check"] is None
    assert len(vision.calls) == 1


def test_manual_fulfillment_retries_a_camera_write_race_and_recovers_duplicate_request():
    class RacingSquare(Square):
        raced = False

        def request(self, request):
            if request.method == "PUT":
                patch = json.loads(request.content)["order"]
                if (
                    patch.get("metadata", {}).get("fullfill_queue_status") == "fulfilled"
                    and not self.raced
                ):
                    self.raced = True
                    # A concurrent camera confirmation wins the first versioned write.
                    record = json.loads(self.order["metadata"][CHECK_KEY])
                    record["s"] = "completed"
                    self.order["metadata"][CHECK_KEY] = json.dumps(record, separators=(",", ":"))
                    self.order["version"] += 1
            return super().request(request)

    square, vision = RacingSquare(), Vision()
    with TestClient(square.app(vision)) as client:
        assert send(client, confirm=False).status_code == 200
        body = {"worker_id": "worker", "status": "fulfilled", "expected_revision": 3}
        result = client.post(
            "/v1/orders/ticket/status", headers={"Idempotency-Key": "manual"}, json=body
        )
        assert result.status_code == 200, result.text
        assert result.json()["disposition"] == "overridden"
        version = square.order["version"]
        duplicate = client.post(
            "/v1/orders/ticket/status", headers={"Idempotency-Key": "manual"}, json=body
        )
        assert duplicate.json() == result.json()
        assert square.order["version"] == version
        assert square.raced


@pytest.mark.parametrize("change", ["ticket", "worker", "manual"])
def test_stale_manual_fulfillment_does_not_overwrite_unrelated_changes(change):
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        assert send(client, confirm=False).status_code == 200
        if change == "ticket":
            square.order["line_items"][0]["quantity"] = "3"
        elif change == "worker":
            square.order["metadata"][CLAIM_KEY] = claim_value("another-worker")
        else:
            updated = client.post(
                "/v1/orders/ticket/status",
                headers={"Idempotency-Key": "newer-manual"},
                json={
                    "worker_id": "worker",
                    "status": "unsure",
                    "expected_revision": square.order["version"],
                },
            )
            assert updated.status_code == 200
        square.order["version"] += 1
        before = copy.deepcopy(square.order)
        result = client.post(
            "/v1/orders/ticket/status",
            headers={"Idempotency-Key": "stale-manual"},
            json={"worker_id": "worker", "status": "fulfilled", "expected_revision": 3},
        )
        assert result.status_code == 409
        assert square.order == before


def test_lost_response_is_recovered_without_another_paid_call():
    square, vision = Square(), Vision()
    square.lose_finish_response = True
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 503
        assert send(client).json()["disposition"] == "verified"
    assert len(vision.calls) == 1


def test_failed_provider_never_goes_green_and_does_not_leak_error_or_retry(caplog):
    class FailedVision(Vision):
        async def inspect(self, request):
            self.calls.append(request)
            raise VisionProviderError("secret-key and raw response")

    square, vision = Square(), FailedVision()
    with TestClient(square.app(vision)) as client:
        result = send(client)
        assert result.status_code == 502
        assert "secret-key" not in result.text
        assert "vision_provider.invalid_response" in result.json()["detail"]
        state = send(client).json()
        assert state["current_check"]["execution_status"] == "failed"
        assert state["disposition"] == "needs_review"
    assert len(vision.calls) == 1
    assert "phase=vision_provider" in caplog.text
    assert "secret-key" not in caplog.text


@pytest.mark.parametrize("status", [401, 429, 503])
def test_provider_http_status_is_diagnostic_without_exposing_response(status):
    class FailedVision(Vision):
        async def inspect(self, request):
            response = httpx.Response(
                status, request=httpx.Request("POST", "https://provider.invalid")
            )
            cause = httpx.HTTPStatusError(
                "secret response", request=response.request, response=response
            )
            raise VisionProviderError("secret-key") from cause

    with TestClient(Square().app(FailedVision())) as client:
        result = send(client)
        assert result.status_code == 502
        assert f"vision_provider.http_{status}" in result.json()["detail"]
        assert "secret" not in result.text


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
    async def unavailable(_url, revision=0):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("fullfill.http.checks.reference_image", unavailable)
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        result = send(client)
        assert result.status_code == 502
        assert "reference_photos.unavailable" in result.json()["detail"]
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
            body = {
                "worker_id": "worker",
                "order_id": "ticket",
                "expected_revision": 3,
                "photo": photo(),
            }
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


def test_uses_saved_ticket_and_alternative_references(monkeypatch):
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

    async def reference(url, revision=0):
        seen.append(url)
        return ImageInput(b"reference", "image/jpeg")

    monkeypatch.setattr(SquareOrders, "menu", menu)
    monkeypatch.setattr("fullfill.http.checks.reference_image", reference)
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 200
    assert len(seen) == 2
    assert {ref.item_id for ref in vision.calls[0].references} == {"fries", "drink"}
    assert {ref.name for ref in vision.calls[0].references} == {"Fries", "Drink"}
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
    square, vision = Square(), Vision(status="unsure")
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
            json={
                "worker_id": "worker",
                "status": "fulfilled",
                "expected_revision": result["order"]["revision"],
            },
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


def test_pending_camera_result_is_never_green_until_same_worker_confirms():
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        state = send(client, confirm=False).json()
        assert state["disposition"] == "pending"
        assert state["current_check"]["execution_status"] == "awaiting_confirmation"
        state.pop("diagnostics")
        assert client.get("/v1/stations/main").json()["orders"][0] == state
        assert confirmation(client, state, worker="other").status_code == 409
        accepted = confirmation(client, state)
        assert accepted.json()["disposition"] == "verified"
        assert confirmation(client, state).json() == accepted.json()
        rejected = confirmation(client, accepted.json(), unchanged=False)
        assert rejected.json()["disposition"] == "needs_review"
        assert rejected.json()["current_check"]["execution_status"] == "superseded"
        assert confirmation(client, rejected.json()).json() == rejected.json()
    assert len(vision.calls) == 1


@pytest.mark.parametrize("expired", [False, True])
def test_changed_scene_or_expired_confirmation_cannot_fulfill(expired, monkeypatch):
    square = Square()
    with TestClient(square.app(Vision())) as client:
        state = send(client, confirm=False).json()
        if expired:
            record = json.loads(square.order["metadata"][CHECK_KEY])
            monkeypatch.setattr(
                "fullfill.adapters.orders.camera_checks.time.time", lambda: record["t"] + 16
            )
            assert (
                client.get("/v1/stations/main").json()["orders"][0]["disposition"] == "needs_review"
            )
        result = confirmation(client, state, unchanged=expired)
        assert result.json()["disposition"] == "needs_review"
        assert result.json()["current_check"]["execution_status"] == "superseded"


def test_late_scene_confirmation_cannot_overwrite_manual_correction_or_ticket_edit():
    for mutate in ("manual", "ticket"):
        square = Square()
        with TestClient(square.app(Vision())) as client:
            state = send(client, confirm=False).json()
            if mutate == "manual":
                assert (
                    client.post(
                        "/v1/orders/ticket/status",
                        headers={"Idempotency-Key": "manual"},
                        json={
                            "worker_id": "worker",
                            "expected_revision": state["order"]["revision"],
                            "status": "unsure",
                        },
                    ).status_code
                    == 200
                )
            else:
                square.order["line_items"][0]["quantity"] = "3"
                square.order["version"] += 1
            assert confirmation(client, state).status_code == 409
            assert client.get("/v1/stations/main").json()["orders"][0]["disposition"] != "verified"


def test_camera_rejects_unclaimed_or_other_workers_before_paid_call():
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        assert send(client, worker="other").status_code == 409
        square.order["metadata"].pop(CLAIM_KEY)
        assert send(client).status_code == 409
    assert not vision.calls


def test_all_unexpected_items_survive_overflow_and_a_later_short_result():
    import random
    import string

    rng = random.Random(12)
    names = ["".join(rng.choices(string.ascii_letters, k=75)) for _ in range(18)]

    class ExtrasVision(Vision):
        async def inspect(self, request):
            observed = await super().inspect(request)
            observed.unexpected_items = [UnexpectedItem(name=name, quantity=2) for name in names]
            return observed

    square, vision = Square(), ExtrasVision(count=1)
    with TestClient(square.app(vision)) as client:
        result = send(client)
        assert result.status_code == 200, result.text
        messages = [item["message"] for item in result.json()["current_check"]["discrepancies"]]
        assert all(any(name in message for message in messages) for name in names)
        assert any(
            key.startswith("fullfill_result_") for key in square.order["line_items"][0]["metadata"]
        )
        with TestClient(square.app()) as other:
            assert other.get("/v1/stations/main").json()["orders"][0] == result.json()
        names.clear()
        shorter = send(client, key="short", revision=square.order["version"])
        assert shorter.status_code == 200, shorter.text
        assert len(shorter.json()["current_check"]["discrepancies"]) == 1
        assert square.order["line_items"][0]["metadata"]["fullfill_item_id"] == "fries"
        assert square.order["line_items"][0]["quantity"] == "2"


def test_duplicate_provider_targets_cannot_be_compacted_into_a_pass():
    class DuplicateVision(Vision):
        async def inspect(self, request):
            observations = await super().inspect(request)
            observations.targets.append(observations.targets[0])
            return observations

    square, vision = Square(), DuplicateVision()
    with TestClient(square.app(vision)) as client:
        assert send(client).status_code == 502
        assert client.get("/v1/stations/main").json()["orders"][0]["disposition"] == "needs_review"
    assert len(vision.calls) == 1


@pytest.mark.parametrize("moment", ["inference", "confirmation"])
def test_reference_photo_change_rejects_old_evidence(monkeypatch, moment):
    version = 1

    async def menu(_source):
        return MenuSnapshot(
            revision=str(version),
            items=[
                MenuEntry(
                    item_id="fries",
                    name="Fries",
                    description="",
                    price_cents=400,
                    version=version,
                    photo_id=f"photo-{version}",
                    photo_url="https://items-images-production.s3.amazonaws.com/fries.jpg",
                )
            ],
        )

    def change_photo():
        nonlocal version
        version += 1

    monkeypatch.setattr(SquareOrders, "menu", menu)
    square, vision = Square(), Vision()
    if moment == "inference":
        vision.before_result = change_photo
    with TestClient(square.app(vision)) as client:
        pending = send(client, confirm=False)
        assert pending.status_code == 200, pending.text
        if moment == "confirmation":
            change_photo()
        result = confirmation(client, pending.json())
        assert result.status_code == 200, result.text
        assert result.json()["disposition"] == "needs_review"
        assert result.json()["current_check"]["error_code"] == "reference_changed"
        assert result.json()["current_check"]["execution_status"] == "superseded"
    assert len(vision.calls) == 1


def test_menu_failure_during_confirmation_cannot_turn_ticket_green(monkeypatch):
    from fullfill.application.order_source import OrderSourceError

    async def unavailable(_source):
        raise OrderSourceError("Menu unavailable", 503)

    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        pending = send(client, confirm=False)
        monkeypatch.setattr(SquareOrders, "menu", unavailable)
        assert confirmation(client, pending.json()).status_code == 503
        assert client.get("/v1/stations/main").json()["orders"][0]["disposition"] != "verified"


def test_wrong_and_unknown_item_details_survive_square_storage():
    class ExtrasVision(Vision):
        async def inspect(self, request):
            observed = await super().inspect(request)
            observed.unexpected_items = [
                UnexpectedItem(
                    name="Chips", item_id="chips", quantity=1, instead_of_target_id="fries"
                ),
                UnexpectedItem(name="Covered container", quantity=1),
            ]
            return observed

    square = Square()
    with TestClient(square.app(ExtrasVision(count=1))) as client:
        result = send(client)
        assert result.status_code == 200, result.text
        issues = result.json()["current_check"]["discrepancies"]
        assert [issue["kind"] for issue in issues] == ["missing", "wrong_item", "unidentified"]
        assert issues[1]["target_id"] == "fries" and issues[1]["observed_quantity"] == 1
    with TestClient(square.app()) as other:
        assert other.get("/v1/stations/main").json()["orders"][0] == result.json()


def test_every_check_returns_model_answer_and_timings_but_no_photos_by_default():
    square, vision = Square(), Vision(status="unsure", unexpected=True)
    with TestClient(square.app(vision)) as client:
        result = send(client, confirm=False)
    diagnostic = result.json()["diagnostics"]
    assert diagnostic["image"] is None
    assert all(ref["image"] is None for ref in diagnostic["references"])
    assert diagnostic["observations"]["targets"][0]["status"] == "unsure"
    assert "perceptron" in diagnostic["timings_ms"]
    assert len(result.content) < 20_000


@pytest.mark.parametrize("fails", [False, True])
def test_visual_diagnostics_return_exact_inputs_without_persisting_photos(fails):
    class DiagnosticVision(Vision):
        async def inspect(self, request):
            result = await super().inspect(request)
            if fails:
                raise VisionProviderError("invalid output")
            return result

    square, vision = Square(), DiagnosticVision(status="unsure", unexpected=True)
    with TestClient(square.app(vision)) as client:
        result = client.post(
            "/v1/checks/camera",
            headers={"Idempotency-Key": "visual"},
            json={
                "worker_id": "worker",
                "order_id": "ticket",
                "expected_revision": 3,
                "photo": photo(),
                "photos": True,
            },
        )
        assert result.status_code == (502 if fails else 200), result.text
        diagnostic = result.json()["diagnostics"]
        supplied = vision.calls[0]
        assert base64.b64decode(diagnostic["image"].split(",")[1]) == supplied.image.data
        assert (
            base64.b64decode(diagnostic["references"][0]["image"].split(",")[1])
            == supplied.references[0].image.data
        )
        assert diagnostic["references"][0]["role"] == "expected"
        assert diagnostic["targets"][0]["expected_quantity"] == 2
        if fails:
            assert diagnostic["observations"] is None
        else:
            assert diagnostic["observations"]["targets"][0]["status"] == "unsure"
            assert diagnostic["observations"]["unexpected_items"][0]["name"] == "Drink"
            assert set(diagnostic["timings_ms"]) == {
                "square_order",
                "square_menu",
                "reference_photos",
                "perceptron",
                "saving_result",
            }
        assert "data:image" not in json.dumps(square.order)
        assert "diagnostics" not in client.get("/v1/stations/main").text
        duplicate = client.post(
            "/v1/checks/camera",
            headers={"Idempotency-Key": "visual"},
            json={
                "worker_id": "worker",
                "order_id": "ticket",
                "expected_revision": 3,
                "photo": photo(),
                "diagnostics": True,
            },
        )
        assert duplicate.status_code == 200
        assert duplicate.json().get("diagnostics") is None
        assert len(vision.calls) == 1


def test_visual_diagnostic_images_are_bounded_without_altering_model_inputs():
    from fullfill.http.camera_diagnostics import input_diagnostics
    from fullfill_contracts.vision import ReferenceImage, VisionInput

    image = ImageInput(b"x" * 1_500_000, "image/jpeg")
    request = VisionInput(
        capture_id="capture",
        image=image,
        targets=(),
        references=(ReferenceImage(item_id="other", revision=2, image=image, name="Other"),),
    )
    result = input_diagnostics(request)
    assert result["image"] is not None
    assert result["references"][0]["image"] is None
    assert result["references"][0]["role"] == "alternative"
    assert len(json.dumps(result)) < 3_100_000
    assert request.references[0].image.data == image.data


def test_diagnostics_keep_model_observations_when_saving_fails(monkeypatch):
    original = SquareOrders.finish_camera_check

    async def fail_save(source, reserved, observations=None, reference_version=None, **_):
        if observations is not None:
            raise ValueError("cannot store this result")
        return await original(source, reserved)

    monkeypatch.setattr(SquareOrders, "finish_camera_check", fail_save)
    vision = Vision()
    with TestClient(Square().app(vision)) as client:
        result = client.post(
            "/v1/checks/camera",
            headers={"Idempotency-Key": "visual-save"},
            json={
                "worker_id": "worker",
                "order_id": "ticket",
                "expected_revision": 3,
                "photo": photo(),
                "diagnostics": True,
            },
        )
    assert result.status_code == 502
    assert "saving_result.invalid_data" in result.json()["detail"]
    assert result.json()["diagnostics"]["observations"]["targets"][0]["status"] == "present"
    assert len(vision.calls) == 1


@pytest.mark.parametrize("count", [2, 1])
def test_kitchen_can_skip_the_confirm_round_trip(count):
    square, vision = Square(), Vision(count=count)
    with TestClient(square.app(vision)) as client:
        result = client.post(
            "/v1/checks/camera",
            headers={"Idempotency-Key": "one-trip"},
            json={
                "worker_id": "worker",
                "order_id": "ticket",
                "expected_revision": 3,
                "photo": photo(),
                "confirmed": True,
            },
        ).json()
        assert result["current_check"]["execution_status"] == "completed"
        assert result["disposition"] == ("verified" if count == 2 else "pending")
        # The kitchen can still withdraw it, e.g. when the tab was hidden mid-check.
        withdrawn = confirmation(client, result, unchanged=False).json()
        assert withdrawn["current_check"]["execution_status"] == "superseded"


def test_unknown_reasoning_effort_is_rejected():
    square, vision = Square(), Vision()
    with TestClient(square.app(vision)) as client:
        result = client.post(
            "/v1/checks/camera",
            headers={"Idempotency-Key": "reasoning"},
            json={
                "worker_id": "worker",
                "order_id": "ticket",
                "expected_revision": 3,
                "photo": photo(),
                "reasoning": "maximum",
            },
        )
    assert result.status_code == 422
    assert not vision.calls
