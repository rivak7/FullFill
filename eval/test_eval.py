"""Offline tests for the eval harness: a fake client, no credits spent.

    python -m unittest eval.test_eval
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

import config
from eval import run, vision

MENU = {"fries": {"name": "Fries"}, "ranch_cup": {"name": "Ranch cup", "description": "white lid"}}


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        choice = SimpleNamespace(finish_reason="stop")
        return SimpleNamespace(text=json.dumps(answer), finish_reason=choice.finish_reason,
                               usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=50))


def answer(**counts):
    return {"items": [{"item_id": i, "status": "present" if c else "missing", "count": c, "label_text": None}
                      for i, c in counts.items()], "unexpected_items": []}


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "order.jpg"
        cv2.imwrite(str(self.image), np.zeros((1080, 1920, 3), np.uint8))
        refs = self.tmp / "refs"
        for item in MENU:
            (refs / item).mkdir(parents=True)
            cv2.imwrite(str(refs / item / "ref_01.jpg"), np.zeros((800, 800, 3), np.uint8))
        patcher = mock.patch.object(config, "REFERENCE_DIR", refs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def guard(self, max_calls=10, max_total=100):
        return vision.CallGuard(max_calls=max_calls, cooldown=0, budget_file=self.tmp / "budget.json",
                                max_total=max_total)

    def test_request_has_schema_refs_and_no_expected_quantities(self):
        client = FakeClient([answer(fries=1, ranch_cup=2)])
        result = vision.check_order(client, self.guard(), self.image, ["fries", "ranch_cup"], MENU)
        self.assertTrue(result.ok)
        req = client.requests[0]
        self.assertEqual(req["response_format"]["json_schema"]["schema"]["properties"]["items"]["items"]
                         ["properties"]["item_id"]["enum"], ["fries", "ranch_cup"])
        self.assertEqual(req["reasoning_effort"], "none")
        images = [p for p in req["messages"][0]["content"] if p["type"] == "image_url"]
        self.assertEqual(len(images), 3)  # two references, then the order photo
        self.assertEqual(result.n_references, 2)

    def test_names_only_sends_just_the_order_photo(self):
        client = FakeClient([answer(fries=1, ranch_cup=1)])
        vision.check_order(client, self.guard(), self.image, ["fries", "ranch_cup"], MENU, use_references=False)
        images = [p for p in client.requests[0]["messages"][0]["content"] if p["type"] == "image_url"]
        self.assertEqual(len(images), 1)

    def test_verdicts(self):
        order = {"fries": 1, "ranch_cup": 2}
        ok = lambda a: vision.CheckResult(ok=True, latency_s=1, items=vision.parse_answer(json.dumps(a), order)[0])
        self.assertEqual(vision.verdict(order, ok(answer(fries=1, ranch_cup=2))), "green")
        self.assertEqual(vision.verdict(order, ok(answer(fries=1, ranch_cup=1))), "red")
        unsure = answer(fries=1, ranch_cup=2)
        unsure["items"][1]["status"] = "unsure"
        self.assertEqual(vision.verdict(order, ok(unsure)), "amber")
        self.assertEqual(vision.verdict(order, vision.CheckResult(ok=False, latency_s=1)), "error")

    def test_invalid_answers_are_rejected(self):
        with self.assertRaises(ValueError):
            vision.parse_answer(json.dumps(answer(fries=1)), ["fries", "ranch_cup"])
        dup = answer(fries=1, ranch_cup=1)
        dup["items"][1]["item_id"] = "fries"
        with self.assertRaises(ValueError):
            vision.parse_answer(json.dumps(dup), ["fries", "ranch_cup"])

    def test_api_error_is_recorded_not_raised(self):
        client = FakeClient([RuntimeError("401 bad key")])
        result = vision.check_order(client, self.guard(), self.image, ["fries"], MENU)
        self.assertFalse(result.ok)
        self.assertIn("bad key", result.error)

    def test_run_cap_and_lifetime_cap(self):
        guard = self.guard(max_calls=2)
        guard.acquire()
        guard.acquire()
        with self.assertRaises(vision.BudgetExceeded):
            guard.acquire()
        later = self.guard(max_calls=10, max_total=3)  # lifetime count persists across runs
        later.acquire()
        with self.assertRaises(vision.BudgetExceeded):
            later.acquire()

    def test_cooldown_waits_between_calls(self):
        slept = []
        guard = vision.CallGuard(max_calls=5, cooldown=2.0, budget_file=self.tmp / "b.json",
                                 clock=lambda: 10.0, sleep=slept.append)
        guard.acquire()
        guard.acquire()
        self.assertEqual(slept, [2.0])

    def test_t2_scoring(self):
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
        self.assertTrue(passed["T2 photos"])
        self.assertFalse(passed["T2 names"])
        self.assertIn("photos fixed 1 ['e']", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
