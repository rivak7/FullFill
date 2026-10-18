"""Offline tests for the eval harness: a fake client, no credits spent.

    python -m pytest eval/test_eval.py
"""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import config
from eval import run, vision

MENU = {"fries": {"name": "Fries"}, "ranch_cup": {"name": "Ranch cup", "description": "white lid"}}


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=json.dumps(answer), finish_reason="stop", request_id=None,
                               usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=50))


def answer(**counts):
    return {"items": [{"item_id": i, "status": "present" if c else "missing", "count": c, "label_text": None}
                      for i, c in counts.items()], "unexpected_items": [], "scene_status": "clear"}


@pytest.fixture
def tmp(tmp_path, monkeypatch):
    refs = tmp_path / "refs"
    for item in MENU:
        (refs / item).mkdir(parents=True)
        cv2.imwrite(str(refs / item / "ref_01.jpg"), np.zeros((800, 800, 3), np.uint8))
    monkeypatch.setattr(config, "REFERENCE_DIR", refs)
    return tmp_path


@pytest.fixture
def image(tmp):
    path = tmp / "order.jpg"
    cv2.imwrite(str(path), np.zeros((1080, 1920, 3), np.uint8))
    return path


def adapter_with(client):
    return vision.adapter.PerceptronVision(client=client, limiter=vision.adapter.CallLimiter(100, 0))


def make_guard(tmp, max_calls=10, max_total=100):
    return vision.CallGuard(max_calls=max_calls, cooldown=0, budget_file=tmp / "budget.json", max_total=max_total)


def test_request_has_schema_refs_and_no_expected_quantities(tmp, image):
    client = FakeClient([answer(fries=1, ranch_cup=2)])
    result = vision.check_order(adapter_with(client), make_guard(tmp), image, ["fries", "ranch_cup"], MENU)
    assert result.ok
    req = client.requests[0]
    assert (req["response_format"]["json_schema"]["schema"]["properties"]["items"]["items"]
            ["properties"]["item_id"]["enum"]) == ["fries", "ranch_cup"]
    assert req["reasoning_effort"] == "none"
    images = [p for p in req["messages"][0]["content"] if p["type"] == "image_url"]
    assert len(images) == 3  # two references, then the order photo
    assert result.n_references == 2


def test_names_only_sends_just_the_order_photo(tmp, image):
    client = FakeClient([answer(fries=1, ranch_cup=1)])
    vision.check_order(adapter_with(client), make_guard(tmp), image, ["fries", "ranch_cup"], MENU, use_references=False)
    images = [p for p in client.requests[0]["messages"][0]["content"] if p["type"] == "image_url"]
    assert len(images) == 1


def test_verdicts():
    order = {"fries": 1, "ranch_cup": 2}
    ok = lambda a: vision.CheckResult(ok=True, latency_s=1, items=vision.parse_answer(json.dumps(a), order)[0])
    assert vision.verdict(order, ok(answer(fries=1, ranch_cup=2))) == "green"
    assert vision.verdict(order, ok(answer(fries=1, ranch_cup=1))) == "red"
    unsure = answer(fries=1, ranch_cup=2)
    unsure["items"][1]["status"] = "unsure"
    assert vision.verdict(order, ok(unsure)) == "amber"
    assert vision.verdict(order, vision.CheckResult(ok=False, latency_s=1)) == "error"


def test_invalid_answers_are_rejected():
    with pytest.raises(ValueError):
        vision.parse_answer(json.dumps(answer(fries=1)), ["fries", "ranch_cup"])
    dup = answer(fries=1, ranch_cup=1)
    dup["items"][1]["item_id"] = "fries"
    with pytest.raises(ValueError):
        vision.parse_answer(json.dumps(dup), ["fries", "ranch_cup"])


def test_api_error_is_recorded_not_raised(tmp, image):
    client = FakeClient([RuntimeError("401 bad key")])
    result = vision.check_order(adapter_with(client), make_guard(tmp), image, ["fries"], MENU)
    assert not result.ok
    assert "bad key" in result.error


def test_run_cap_and_lifetime_cap(tmp):
    guard = make_guard(tmp, max_calls=2)
    guard.acquire()
    guard.acquire()
    with pytest.raises(vision.BudgetExceeded):
        guard.acquire()
    later = make_guard(tmp, max_calls=10, max_total=3)  # lifetime count persists across runs
    later.acquire()
    with pytest.raises(vision.BudgetExceeded):
        later.acquire()


def test_cooldown_waits_between_calls(tmp):
    slept = []
    guard = vision.CallGuard(max_calls=5, cooldown=2.0, budget_file=tmp / "b.json",
                             clock=lambda: 10.0, sleep=slept.append)
    guard.acquire()
    guard.acquire()
    assert slept == [2.0]


def test_t2_scoring():
    err = {"id": "e", "test": "t2", "order": {"fries": 1, "ranch_cup": 2},
           "actual": {"fries": 1, "ranch_cup": 1}, "extras": []}
    good = {"id": "g", "test": "t2", "order": {"fries": 1, "ranch_cup": 1},
            "actual": {"fries": 1, "ranch_cup": 1}, "extras": []}
    res = lambda a, order: vision.CheckResult(ok=True, latency_s=2.0,
                                              items=vision.parse_answer(json.dumps(a), order)[0])
    records = [run.record(err, "photos", res(answer(fries=1, ranch_cup=1), err["order"]), 1),
               run.record(good, "photos", res(answer(fries=1, ranch_cup=1), good["order"]), 2),
               run.record(err, "names", res(answer(fries=1, ranch_cup=2), err["order"]), 3),
               run.record(good, "names", res(answer(fries=1, ranch_cup=1), good["order"]), 4)]
    lines, passed = run.summarize(records)
    assert passed["T2 photos"]
    assert not passed["T2 names"]
    assert "photos fixed 1 ['e']" in "\n".join(lines)



def test_nonordered_references_and_structured_wrong_items_reach_the_verdict(tmp, image):
    data = answer(fries=1)
    data["unexpected_items"] = [{"item_id": "ranch_cup", "name": "Ranch", "count": 1,
                                 "instead_of_target_id": None, "label_text": None}]
    client = FakeClient([data])
    result = vision.check_order(adapter_with(client), make_guard(tmp), image, ["fries"], MENU)
    assert result.n_references == 2
    assert result.unexpected[0]["item_id"] == "ranch_cup"
    assert vision.verdict({"fries": 1}, result) == "red"
    assert len(client.requests) == 1


def test_obscured_scene_survives_evaluation_scoring(tmp, image):
    data = answer(fries=1)
    data["scene_status"] = "obscured"
    client = FakeClient([data])
    result = vision.check_order(adapter_with(client), make_guard(tmp), image, ["fries"], MENU)
    assert result.scene_uncertainty
    assert vision.verdict({"fries": 1}, result) == "amber"
