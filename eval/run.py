"""Go/no-go tests T1-T3 against the real Perceptron API.

    python -m eval.run ping                  # one call, to check the key and request format
    python -m eval.run t1                    # 20 latency calls on one order photo
    python -m eval.run t2 --mode both        # accuracy, names-only and names-plus-photos
    python -m eval.run t3 --mode both        # lookalikes and marker labels
    python -m eval.run t2 --dry-run          # build every request, spend nothing
    python -m eval.run summarize logs/eval/<run>.jsonl

Cases come from eval/manifest.json (copy eval/manifest.example.json). Every call
is logged to logs/eval/ so results can be re-scored without new calls.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import config
from eval import vision

ROOT = config.ROOT
RUN_DIR = config.LOG_DIR / "eval"
DEFAULT_MANIFEST = ROOT / "eval" / "manifest.json"
MAX_CONSECUTIVE_ERRORS = 3

# Pass criteria from order-checker.md, "Pass/fail tests".
T1_MEDIAN_S = 4.0
T1_P90_S = 8.0
T2_MIN_CATCH = 0.8          # 16 of 20 errors
T2_MAX_FALSE_ALARM = 0.2    # 2 of 10 correct orders
T3_MIN_RATE = 0.9           # 9 of 10


def load_manifest(path):
    data = json.loads(Path(path).read_text())
    menu, cases = data["menu"], data["cases"]
    problems = []
    for case in cases:
        case.setdefault("actual", dict(case["order"]))
        case.setdefault("extras", [])
        image = ROOT / case["image"]
        if not image.exists():
            problems.append(f"{case['id']}: image {case['image']} not found")
        for item_id in set(case["order"]) | set(case["actual"]):
            if item_id not in menu:
                problems.append(f"{case['id']}: {item_id} is not in the menu")
        if set(case["actual"]) - set(case["order"]):
            problems.append(f"{case['id']}: 'actual' lists items not on the order; put them in 'extras'")
    if problems:
        raise SystemExit("Manifest problems:\n  " + "\n  ".join(problems))
    return menu, cases


def missing_references(cases, refs_per_item):
    needed = {item_id for case in cases for item_id in case["order"]}
    return sorted(i for i in needed if not vision.reference_photos(i, refs_per_item))


def is_error_case(case):
    return case["actual"] != case["order"] or bool(case["extras"])


def percentile(values, p):
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def norm_label(text):
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def record(case, mode, result, call_index, test=None):
    color = vision.verdict(case["order"], result)
    counts_right = result.ok and all(
        result.items[i]["count"] == case["actual"].get(i, 0) for i in case["order"])
    labels = case.get("labels") or {}
    labels_right = {i: result.ok and norm_label(result.items[i]["label_text"]) == norm_label(t)
                    for i, t in labels.items()}
    return {
        "case": case["id"], "test": test or case["test"], "kind": case.get("kind"), "mode": mode,
        "call": call_index, "error_case": is_error_case(case), "verdict": color,
        "counts_right": counts_right, "labels_right": labels_right,
        "latency_s": round(result.latency_s, 3), "ok": result.ok, "error": result.error,
        "items": result.items, "unexpected": result.unexpected, "raw": result.raw,
        "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
        "cost": result.cost, "n_references": result.n_references,
        "prompt_version": vision.PROMPT_VERSION,
    }


def summarize(records):
    lines = []
    passed = {}
    ok = [r for r in records if r["ok"]]
    failed = len(records) - len(ok)
    costs = [r["cost"] for r in records if r["cost"] is not None]
    lines.append(f"Calls: {len(records)} ({failed} failed or invalid)")
    if costs:
        prompt = statistics.mean(r["prompt_tokens"] for r in records if r["prompt_tokens"] is not None)
        lines.append(f"Cost: ${sum(costs):.4f} total, ${statistics.mean(costs):.4f} per check, "
                     f"about {prompt:.0f} input tokens per check")

    t1 = [r["latency_s"] for r in ok if r["test"] == "t1"]
    if t1:
        med, p90 = statistics.median(t1), percentile(t1, 0.9)
        passed["T1"] = med <= T1_MEDIAN_S and p90 <= T1_P90_S
        refs = sorted({r["n_references"] for r in records if r["test"] == "t1"})
        lines.append(f"T1 latency: median {med:.2f} s, p90 {p90:.2f} s, min {min(t1):.2f}, max {max(t1):.2f} "
                     f"over {len(t1)} calls with {refs} reference photos -> {'PASS' if passed['T1'] else 'FAIL'} "
                     f"(needs median <= {T1_MEDIAN_S:g} s and p90 <= {T1_P90_S:g} s)")
    all_lat = [r["latency_s"] for r in ok]
    if all_lat and not t1:
        lines.append(f"Latency over all calls: median {statistics.median(all_lat):.2f} s, "
                     f"p90 {percentile(all_lat, 0.9):.2f} s")

    for mode in ("photos", "names"):
        rows = [r for r in records if r["mode"] == mode]
        t2 = [r for r in rows if r["test"] == "t2"]
        if t2:
            errs = [r for r in t2 if r["error_case"]]
            good = [r for r in t2 if not r["error_case"]]
            # Flagged = anything but green. Amber still stops the bag for a human look.
            caught = sum(r["verdict"] in ("red", "amber") for r in errs)
            caught_red = sum(r["verdict"] == "red" for r in errs)
            alarms = sum(r["verdict"] in ("red", "amber") for r in good)
            alarms_red = sum(r["verdict"] == "red" for r in good)
            exact = sum(r["counts_right"] for r in t2)
            calls_failed = sum(r["verdict"] == "error" for r in t2)
            ok_catch = bool(errs) and caught / len(errs) >= T2_MIN_CATCH
            ok_alarm = bool(good) and alarms / len(good) <= T2_MAX_FALSE_ALARM
            passed[f"T2 {mode}"] = ok_catch and ok_alarm
            lines.append(
                f"T2 accuracy ({mode}): caught {caught}/{len(errs)} errors ({caught_red} red), "
                f"false alarms {alarms}/{len(good)} ({alarms_red} red), exact counts {exact}/{len(t2)}, "
                f"failed calls {calls_failed} -> {'PASS' if passed[f'T2 {mode}'] else 'FAIL'}")
        t3 = [r for r in rows if r["test"] == "t3"]
        if t3:
            look = [r for r in t3 if r["kind"] == "lookalike"]
            labels = [ok_ for r in t3 if r["kind"] == "label" for ok_ in r["labels_right"].values()]
            look_ok = sum(r["counts_right"] for r in look)
            parts, results = [], []
            if look:
                rate = look_ok / len(look)
                results.append(rate >= T3_MIN_RATE)
                parts.append(f"lookalikes right {look_ok}/{len(look)}")
            if labels:
                rate = sum(labels) / len(labels)
                results.append(rate >= T3_MIN_RATE)
                parts.append(f"labels read {sum(labels)}/{len(labels)}")
            passed[f"T3 {mode}"] = any(results)
            lines.append(f"T3 ({mode}): {', '.join(parts)} -> {'PASS' if passed[f'T3 {mode}'] else 'FAIL'} "
                         f"(needs either at >= {T3_MIN_RATE:.0%})")

    for test in ("t2", "t3"):
        by_case = {}
        for r in records:
            if r["test"] == test:
                by_case.setdefault(r["case"], {})[r["mode"]] = r["counts_right"]
        both = {c: m for c, m in by_case.items() if {"photos", "names"} <= set(m)}
        if both:
            only_photos = sorted(c for c, m in both.items() if m["photos"] and not m["names"])
            only_names = sorted(c for c, m in both.items() if m["names"] and not m["photos"])
            lines.append(f"{test.upper()} photos vs names-only: photos fixed {len(only_photos)} "
                         f"{only_photos}, photos broke {len(only_names)} {only_names}")
    return lines, passed


def planned_calls(args, cases):
    if args.test == "ping":
        return 1
    if args.test == "t1":
        return args.n
    per_case = 2 if args.mode == "both" else 1
    return len(cases) * per_case


def select_cases(args, cases):
    if args.case:
        picked = [c for c in cases if c["id"] in args.case]
        if len(picked) != len(set(args.case)):
            raise SystemExit(f"unknown case id in {args.case}")
        return picked
    if args.test in ("ping", "t1"):
        pool = [c for c in cases if c["test"] == "t1"] or cases
        return pool[:1]
    return [c for c in cases if c["test"] == args.test]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("test", choices=["ping", "t1", "t2", "t3", "summarize"])
    parser.add_argument("log", nargs="?", help="for summarize: a .jsonl file from logs/eval/")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--mode", choices=["photos", "names", "both"], default="photos",
                        help="photos = names plus reference photos; names = names only")
    parser.add_argument("--refs-per-item", type=int, default=1)
    parser.add_argument("--n", type=int, default=20, help="T1 calls")
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument("--max-calls", type=int, help="hard cap for this run (default: exactly the planned calls)")
    parser.add_argument("--cooldown", type=float, help="seconds between calls "
                        f"(default {60 / config.MAX_CALLS_PER_MINUTE:g}, from MAX_CALLS_PER_MINUTE)")
    parser.add_argument("--model", help="model id (default PERCEPTRON_MODEL or perceptron-mk1.5)")
    parser.add_argument("--dry-run", action="store_true", help="build requests without calling the API")
    args = parser.parse_args(argv)

    if args.test == "summarize":
        if not args.log:
            parser.error("summarize needs a log file")
        records = [json.loads(line) for line in Path(args.log).read_text().splitlines() if line.strip()]
        print("\n".join(summarize(records)[0]))
        return 0

    menu, cases = load_manifest(args.manifest)
    cases = select_cases(args, cases)
    if not cases:
        raise SystemExit(f"no {args.test} cases in the manifest")
    modes = ["photos", "names"] if args.mode == "both" else [args.mode]
    if args.test == "ping":
        modes = ["photos"] if args.mode != "names" else ["names"]
    if "photos" in modes:
        missing = missing_references(cases, args.refs_per_item)
        if missing:
            raise SystemExit(f"no reference photos in {config.REFERENCE_DIR} for: {', '.join(missing)}")

    planned = planned_calls(args, cases)
    max_calls = min(args.max_calls, planned) if args.max_calls else planned
    guard = vision.CallGuard(max_calls=max_calls, cooldown=args.cooldown)
    print(f"{args.test}: {planned} calls planned, run cap {max_calls}, "
          f"{guard.total_used()}/{guard.max_total} lifetime eval calls used, cooldown {guard.cooldown:g} s")

    if args.dry_run:
        for case in cases:
            for mode in modes:
                ids = list(case["order"])
                messages, n_refs = vision.build_messages(ROOT / case["image"], ids, menu,
                                                         mode == "photos", args.refs_per_item)
                size = len(json.dumps(messages))
                print(f"  {case['id']} [{mode}]: {len(ids)} items, {n_refs} reference photos, "
                      f"{size / 1024:.0f} KB request")
        return 0

    client = vision.make_client()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUN_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{args.test}.jsonl"
    records = []
    jobs = ([(cases[0], modes[0])] * args.n if args.test == "t1"
            else [(case, mode) for case in cases for mode in modes])
    consecutive_errors = 0
    with log_path.open("w") as log:
        for index, (case, mode) in enumerate(jobs, 1):
            try:
                result = vision.check_order(client, guard, ROOT / case["image"], list(case["order"]), menu,
                                            use_references=mode == "photos",
                                            refs_per_item=args.refs_per_item, model=args.model)
            except vision.BudgetExceeded as exc:
                print(f"Stopped: {exc}")
                break
            row = record(case, mode, result, index, test=args.test if args.test in ("ping", "t1") else None)
            records.append(row)
            log.write(json.dumps(row) + "\n")
            log.flush()
            status = row["verdict"] if result.ok else f"FAILED {result.error}"
            print(f"  [{index}/{len(jobs)}] {case['id']} {mode}: {result.latency_s:.2f} s, {status}")
            consecutive_errors = 0 if result.ok else consecutive_errors + 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"Stopped after {MAX_CONSECUTIVE_ERRORS} failed calls in a row. Last error: {result.error}")
                break

    if args.test == "ping" and records:
        print(json.dumps(records[0]["items"], indent=2), records[0]["unexpected"])
    lines, passed = summarize(records)
    print("\n" + "\n".join(lines))
    print(f"\nLog: {log_path.relative_to(ROOT)}")
    return 0 if all(passed.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
