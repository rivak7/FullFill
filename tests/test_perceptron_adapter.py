import asyncio
import json
from types import SimpleNamespace

import pytest
from fullfill.adapters.vision.perceptron import (
    CallLimiter,
    PerceptronVision,
    VisionCallRejected,
    VisionProviderError,
)
from fullfill_contracts.vision import ImageInput, ReferenceImage, VerificationTarget, VisionInput

IMAGE = ImageInput(data=b"\xff\xd8fake", media_type="image/jpeg")


def target(item_id, name, mode="visible_item", aliases=()):
    return VerificationTarget(
        target_id=item_id,
        line_ids=[f"line-{item_id}"],
        item_id=item_id,
        name=name,
        expected_quantity=1,
        verification_mode=mode,
        label_aliases=list(aliases),
    )


REQUEST = VisionInput(
    capture_id="cap-1",
    image=IMAGE,
    targets=(
        target("chicken_burrito", "Chicken burrito", "label", ["C"]),
        target("mayo", "Mayo packet"),
    ),
    references=(ReferenceImage(item_id="mayo", revision=1, image=IMAGE),),
)


def entry(item_id, status="present", count=1, label=None, unlabeled=0):
    return {
        "item_id": item_id,
        "status": status,
        "count": count,
        "label_text": label,
        "unlabeled_count": unlabeled,
    }


class FakeClient:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(
            text=json.dumps(answer),
            finish_reason="stop",
            request_id="req-1",
            usage=SimpleNamespace(prompt_tokens=1800, completion_tokens=40),
        )


def vision(client, **kwargs):
    limiter = kwargs.pop("limiter", CallLimiter(max_calls=10, cooldown_s=0))
    return PerceptronVision(client=client, limiter=limiter, **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_request_shape():
    client = FakeClient(
        {"items": [entry("chicken_burrito", label="C"), entry("mayo")], "unexpected_items": []}
    )
    obs = run(vision(client).inspect(REQUEST))
    sent = client.requests[0]
    schema = sent["response_format"]["json_schema"]
    assert schema["strict"] is True
    enum = schema["schema"]["properties"]["items"]["items"]["properties"]["item_id"]["enum"]
    assert enum == ["chicken_burrito", "mayo"]
    assert sent["reasoning_effort"] == "none"
    parts = sent["messages"][0]["content"]
    images = [p for p in parts if p["type"] == "image_url"]
    assert len(images) == 2  # one reference, then the order photo last
    prompt = parts[-1]["text"]
    assert 'LABEL REQUIRED: only count it if marked "C"' in prompt
    assert "quantity" not in prompt.lower()
    assert obs.targets[0].label_text == "C"
    assert obs.provider.prompt_tokens == 1800


def test_unlabeled_lookalike_becomes_unsure():
    client = FakeClient(
        {
            "items": [entry("chicken_burrito", count=0, unlabeled=1), entry("mayo")],
            "unexpected_items": [],
        }
    )
    obs = run(vision(client).inspect(REQUEST))
    burrito = obs.targets[0]
    assert burrito.status == "unsure"
    assert "unlabeled" in burrito.reason


def test_answer_missing_a_target_is_rejected():
    client = FakeClient({"items": [entry("mayo")], "unexpected_items": []})
    with pytest.raises(VisionProviderError, match="left out"):
        run(vision(client).inspect(REQUEST))


def test_api_error_is_wrapped():
    client = FakeClient(RuntimeError("401 bad key"))
    with pytest.raises(VisionProviderError, match="bad key"):
        run(vision(client).inspect(REQUEST))


def test_call_cap_stops_before_sending():
    answer = {"items": [entry("chicken_burrito"), entry("mayo")], "unexpected_items": []}
    client = FakeClient(answer, answer)
    adapter = vision(client, limiter=CallLimiter(max_calls=1, cooldown_s=0))
    run(adapter.inspect(REQUEST))
    with pytest.raises(VisionCallRejected):
        run(adapter.inspect(REQUEST))
    assert len(client.requests) == 1


def test_cooldown_waits(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    limiter = CallLimiter(max_calls=5, cooldown_s=2.0, clock=lambda: 10.0)
    run(limiter.acquire())
    run(limiter.acquire())
    assert slept == [2.0]
