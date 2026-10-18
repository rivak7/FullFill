import asyncio
import json
from types import SimpleNamespace

import pytest
from fullfill.adapters.vision.perceptron import (
    CallLimiter,
    PerceptronVision,
    VisionCallRejected,
    VisionProviderError,
    parse_answer,
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
        answer.setdefault("scene_status", "clear")
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
        {"items": [entry("chicken_burrito", label="C"), entry("mayo")], "unknown_items": []}
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
            "items": [
                entry("chicken_burrito", status="unsure", count=0, unlabeled=1),
                entry("mayo"),
            ],
            "unexpected_items": [],
        }
    )
    obs = run(vision(client).inspect(REQUEST))
    burrito = obs.targets[0]
    assert burrito.status == "unsure"
    assert "unlabeled" in burrito.reason


def test_ordered_item_left_out_of_the_answer_is_unsure_not_a_failed_check():
    client = FakeClient({"items": [entry("mayo")], "unexpected_items": []})
    obs = run(vision(client).inspect(REQUEST))
    assert [(t.status, t.observed_quantity) for t in obs.targets] == [
        ("unsure", None),
        ("present", 1),
    ]


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (entry("mayo", "missing", None), None, ("missing", 0)),
        (entry("mayo", count=0), None, ("unsure", None)),
        (entry("mayo", "missing", 1), None, ("unsure", 1)),
        (entry("mayo"), entry("mayo", "missing", 0), ("unsure", 1)),
    ],
)
def test_self_contradicting_answers_become_unsure(first, second, expected):
    items = [entry("chicken_burrito", label="C"), first, *([second] if second else [])]
    observations, _ = parse_answer(json.dumps({"items": items, "unknown_items": []}), REQUEST)
    mayo = observations[1]
    assert (mayo.status, mayo.observed_quantity) == expected


def test_rejected_answer_keeps_the_model_text_and_a_reason_for_the_kitchen():
    client = FakeClient({"items": [None], "unknown_items": []})
    with pytest.raises(VisionProviderError) as caught:
        run(vision(client).inspect(REQUEST))
    assert '"items": [null]' in caught.value.raw_answer
    assert "requested JSON" in caught.value.public_reason


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


def test_website_adapter_has_no_default_spending_cap():
    answer = {"items": [entry("chicken_burrito", label="C"), entry("mayo")], "unexpected_items": []}
    client = FakeClient(*[answer.copy() for _ in range(501)])
    adapter = PerceptronVision(client=client)

    async def checks():
        for _ in range(501):
            await adapter.inspect(REQUEST)

    run(checks())
    assert len(client.requests) == 501


def test_cooldown_waits(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    limiter = CallLimiter(max_calls=5, cooldown_s=2.0, clock=lambda: 10.0)
    run(limiter.acquire())
    run(limiter.acquire())
    assert slept == [2.0]


@pytest.mark.parametrize("label", [None, "", "Beef", "Chocolate"])
def test_label_required_cannot_pass_without_a_matching_readable_label(label):
    client = FakeClient(
        {"items": [entry("chicken_burrito", label=label), entry("mayo")], "unexpected_items": []}
    )
    obs = run(vision(client).inspect(REQUEST))
    assert obs.targets[0].status == "unsure"
    assert "label" in obs.targets[0].reason
    assert len(client.requests) == 1


@pytest.mark.parametrize("scene", ["obscured", "blurry", "out_of_frame", "mixed_orders"])
def test_poor_scene_is_reported_once_without_rewriting_counts(scene):
    client = FakeClient(
        {
            "items": [entry("chicken_burrito", label="C"), entry("mayo", "missing", 0)],
            "unexpected_items": [],
            "scene_status": scene,
        }
    )
    obs = run(vision(client).inspect(REQUEST))
    assert obs.scene_uncertainty
    # The verdict (amber, or red if something is definitely missing) is compare_order's job.
    assert [target.status for target in obs.targets] == ["present", "missing"]


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"items": [None], "unexpected_items": []},
        {"items": [], "unexpected_items": [{}]},
        {"items": [entry("chicken_burrito", count=True), entry("mayo")], "unexpected_items": []},
        {"items": [entry("chicken_burrito", unlabeled="1"), entry("mayo")], "unexpected_items": []},
    ],
)
def test_malformed_observations_are_rejected(bad):
    with pytest.raises(VisionProviderError):
        parse_answer(json.dumps(bad), REQUEST)


def test_uncertainty_reason_overrides_an_apparently_matching_count():
    item = {**entry("chicken_burrito", label="C"), "reason": "identity"}
    observations, _ = parse_answer(
        json.dumps({"items": [item, entry("mayo")], "unexpected_items": []}), REQUEST
    )
    assert observations[0].status == "unsure"
    assert "hidden contents" in observations[0].reason


def test_label_without_aliases_must_name_the_item_not_just_contain_text():
    request = VisionInput(
        capture_id="label", image=IMAGE, targets=(target("fries", "Fries", "label"),), references=()
    )
    for label, expected in [("Order 123", "unsure"), ("Fries", "present")]:
        observations, _ = parse_answer(
            json.dumps({"items": [entry("fries", label=label)], "unexpected_items": []}), request
        )
        assert observations[0].status == expected


def alternative_request(mode="visible_item"):
    return VisionInput(
        capture_id="alternatives",
        image=IMAGE,
        targets=(target("fries", "Fries"),),
        references=(
            ReferenceImage(
                item_id="chips", name="Chips", revision=1, image=IMAGE, verification_mode=mode
            ),
        ),
    )


def alternative_answer(**changes):
    extra = {
        "name": "Model nickname",
        "item_id": "chips",
        "count": 1,
        "instead_of_target_id": "fries",
        "label_text": None,
        **changes,
    }
    return {
        "items": [entry("fries", "missing", 0)],
        "unexpected_items": [extra],
        "scene_status": "clear",
    }


def test_prompt_lists_ordered_items_and_lookalikes_alike():
    answer = {
        "items": [entry("fries", "missing", 0), entry("chips")],
        "unknown_items": [],
        "scene_status": "clear",
    }
    client = FakeClient(answer)
    observed = run(vision(client).inspect(alternative_request()))
    assert len(client.requests) == 1
    sent = client.requests[0]
    schema = sent["response_format"]["json_schema"]["schema"]["properties"]
    assert schema["items"]["items"]["properties"]["item_id"]["enum"] == ["chips", "fries"]
    prompt = sent["messages"][0]["content"][-1]["text"]
    assert "- chips: Chips\n- fries: Fries" in prompt
    assert "ORDERED" not in prompt and "ALTERNATIVE" not in prompt
    extra = observed.unexpected_items[0]
    assert (extra.name, extra.item_id, extra.quantity, extra.instead_of_target_id) == (
        "Chips",
        "chips",
        1,
        None,
    )


@pytest.mark.parametrize(
    "chips,mode,identified",
    [
        (entry("chips"), "visible_item", True),
        (entry("chips", "unsure", 1), "visible_item", False),
        (entry("chips"), "label", False),
        (entry("chips", label="Chips"), "label", True),
    ],
)
def test_a_lookalike_is_named_only_when_seen_clearly(chips, mode, identified):
    answer = {"items": [entry("fries"), chips], "unknown_items": [], "scene_status": "clear"}
    _, extras = parse_answer(json.dumps(answer), alternative_request(mode))
    assert extras[0].name == "Chips"
    assert (extras[0].item_id == "chips") is identified


def test_a_lookalike_the_model_is_unsure_about_without_a_count_is_not_shown():
    answer = {
        "items": [entry("fries"), entry("chips", "unsure", None)],
        "unknown_items": [],
        "scene_status": "clear",
    }
    _, extras = parse_answer(json.dumps(answer), alternative_request())
    assert extras == []


def test_a_missing_lookalike_is_not_reported():
    answer = {
        "items": [entry("fries"), entry("chips", "missing", 0)],
        "unknown_items": [{"name": "Cup", "count": 1, "label_text": None}],
        "scene_status": "clear",
    }
    _, extras = parse_answer(json.dumps(answer), alternative_request())
    assert [(extra.name, extra.item_id) for extra in extras] == [("Cup", None)]


@pytest.mark.parametrize(
    "changes",
    [
        {"item_id": "invented"},
        {"item_id": "fries"},
        {"count": True},
        {"count": -1},
        {"instead_of_target_id": "invented"},
    ],
)
def test_invalid_alternative_identity_and_counts_are_rejected(changes):
    with pytest.raises(VisionProviderError):
        parse_answer(json.dumps(alternative_answer(**changes)), alternative_request())


def test_unreadable_alternative_label_is_unidentified_not_a_forced_match():
    _, extras = parse_answer(json.dumps(alternative_answer()), alternative_request("label"))
    assert extras[0].item_id is None and extras[0].instead_of_target_id is None
    _, extras = parse_answer(
        json.dumps(alternative_answer(label_text="Chips")), alternative_request("label")
    )
    assert extras[0].item_id == "chips"


def test_unknown_item_never_keeps_a_speculative_substitution():
    _, extras = parse_answer(json.dumps(alternative_answer(item_id=None)), alternative_request())
    assert extras[0].name == "Model nickname"
    assert extras[0].item_id is None and extras[0].instead_of_target_id is None


def test_boxes_are_requested_in_same_call_and_linked_to_observed_items():
    box = {"x_min": 120, "y_min": 230, "x_max": 450, "y_max": 670}
    mayo = {**entry("mayo"), "boxes": [box]}
    client = FakeClient(
        {
            "items": [entry("chicken_burrito", label="C"), mayo],
            "unknown_items": [
                {"name": "Unknown cup", "count": 1, "label_text": None, "boxes": [box]}
            ],
        }
    )
    observed = run(vision(client, boxes=True).inspect(REQUEST))
    assert len(client.requests) == 1
    sent = client.requests[0]
    schema = sent["response_format"]["json_schema"]["schema"]["properties"]
    assert "boxes" in schema["items"]["items"]["required"]
    assert "boxes" in schema["unknown_items"]["items"]["required"]
    assert "ONLY in the LAST image" in sent["messages"][0]["content"][-1]["text"]
    assert observed.targets[1].boxes[0].model_dump() == box
    assert observed.unexpected_items[0].boxes[0].model_dump() == box
    assert observed.provider.prompt_tokens == 1800
    assert observed.provider.completion_tokens == 40


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "box",
        [{"x_min": -1, "y_min": 0, "x_max": 20, "y_max": 30}],
        [{"x_min": 20, "y_min": 0, "x_max": 10, "y_max": 30}],
        [{"x_min": 0, "y_min": 0, "x_max": 1001, "y_max": 30}],
        [{"x_min": True, "y_min": 0, "x_max": 20, "y_max": 30}],
        [{"x_min": 0, "y_min": 5, "x_max": 20, "y_max": 5}],
    ],
)
def test_bad_optional_boxes_do_not_invalidate_recognition(bad):
    observed, _ = parse_answer(
        json.dumps(
            {
                "items": [entry("chicken_burrito", label="C"), {**entry("mayo"), "boxes": bad}],
                "unexpected_items": [],
            }
        ),
        REQUEST,
    )
    assert observed[1].status == "present"
    assert observed[1].observed_quantity == 1
    assert observed[1].boxes == []


def test_missing_items_never_get_boxes():
    observed, _ = parse_answer(
        json.dumps(
            {
                "items": [
                    entry("chicken_burrito", label="C"),
                    {
                        **entry("mayo", "missing", 0),
                        "boxes": [{"x_min": 0, "y_min": 0, "x_max": 20, "y_max": 30}],
                    },
                ],
                "unexpected_items": [],
            }
        ),
        REQUEST,
    )
    assert observed[1].boxes == []


def test_rate_limit_spaces_calls_one_second_apart_without_a_cap(monkeypatch):
    now = [100.0]
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    limiter = CallLimiter(max_calls=None, cooldown_s=1.0, clock=lambda: now[0])
    for _ in range(3):
        run(limiter.acquire())
        now[0] += 0.25  # the next request arrives a quarter second later
    assert waits == [0.75, 0.75]
    assert limiter.calls == 3


def test_boxes_are_left_out_unless_asked_for():
    client = FakeClient(
        {"items": [entry("chicken_burrito", label="C"), entry("mayo")], "unknown_items": []}
    )
    observed = run(vision(client).inspect(REQUEST))
    sent = client.requests[0]
    schema = sent["response_format"]["json_schema"]["schema"]["properties"]
    assert "boxes" not in schema["items"]["items"]["properties"]
    assert "boxes" not in schema["unknown_items"]["items"]["properties"]
    assert "boxes" not in sent["messages"][0]["content"][-1]["text"]
    assert observed.provider.prompt_version == "order-check-v9-full-frame"


@pytest.mark.parametrize("effort", ["low", "high"])
def test_reasoning_setting_is_sent_and_recorded(effort):
    client = FakeClient(
        {"items": [entry("chicken_burrito", label="C"), entry("mayo")], "unknown_items": []}
    )
    observed = run(vision(client, reasoning=effort).inspect(REQUEST))
    assert client.requests[0]["reasoning_effort"] == effort
    assert observed.provider.prompt_version == f"order-check-v9-full-frame-reasoning-{effort}"
