"""Decision rules: turn an order plus vision observations into green / red / amber.

This is the only place verdicts are decided. Adapters and storage report what was seen.

Matches the comparison rules in docs/system-design.md:

- fail (red): a ticket item is definitely short or over its quantity, or a known menu item
  that isn't on the ticket is on the mat. Red wins: it stays red even if something else is
  unsure or the view is poor.
- unsure (amber): anything else the worker should look at: an item the model couldn't see,
  count or tell apart, an unlabeled lookalike, an object it can't identify, a line that
  needs manual review. The worker decides. A poor view of the scene is shown alongside
  those, but on its own it doesn't block green: when every ticket item was counted
  exactly and nothing else was seen, the order is complete whatever the scene note says.
- pass (green): every count matches and nothing above applies.
"""

import hashlib
import json
from collections.abc import Mapping

from fullfill_contracts.checks import Comparison, Discrepancy
from fullfill_contracts.orders import MenuItem, OrderSnapshot
from fullfill_contracts.vision import Observations, VerificationTarget


def targets_for(
    order: OrderSnapshot, menu: Mapping[str, MenuItem] | None = None
) -> tuple[VerificationTarget, ...]:
    """Combine identical lines only; variants/modifiers remain distinct targets."""

    def signature(line):
        item = (menu or {}).get(line.item_id)
        return (
            line.item_id,
            line.name,
            item.verification_mode if item else line.verification_mode,
            line.requires_manual_review,
        )

    variants = {}
    for line in order.lines:
        variants.setdefault(line.item_id, set()).add(signature(line))
    grouped: dict[tuple, VerificationTarget] = {}
    for line in order.lines:
        key = signature(line)
        existing = grouped.get(key)
        if existing is not None:
            grouped[key] = existing.model_copy(
                update={
                    "line_ids": [*existing.line_ids, line.line_id],
                    "expected_quantity": existing.expected_quantity + line.quantity,
                }
            )
            continue
        item = (menu or {}).get(line.item_id)
        mode = item.verification_mode if item else line.verification_mode
        target_id = line.item_id
        if len(variants[line.item_id]) > 1:
            target_id += ":" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
        grouped[key] = VerificationTarget(
            target_id=target_id,
            line_ids=[line.line_id],
            item_id=line.item_id,
            name=line.name,
            expected_quantity=line.quantity,
            verification_mode=mode,
            label_aliases=list(item.label_aliases) if item else [],
        )
    return tuple(grouped.values())


def compare_order(
    order: OrderSnapshot,
    observations: Observations,
    menu: Mapping[str, MenuItem] | None = None,
) -> Comparison:
    """Validate/aggregate the checklist without performing I/O."""
    targets = targets_for(order, menu)
    seen = {o.target_id: o for o in observations.targets}
    if len(seen) != len(observations.targets) or set(seen) != {t.target_id for t in targets}:
        raise ValueError("observations must cover each target exactly once")

    discrepancies: list[Discrepancy] = []
    definite = False
    for target in targets:
        obs = seen[target.target_id]
        expected, observed = target.expected_quantity, obs.observed_quantity
        if (obs.status == "missing" and observed != 0) or (
            obs.status == "present" and observed is not None and observed == 0
        ):
            raise ValueError("inconsistent observation status and count")
        common = {"target_id": target.target_id, "line_ids": target.line_ids}
        if obs.status == "unsure" or observed is None:
            discrepancies.append(
                Discrepancy(
                    **common,
                    kind="unsure",
                    message=f"Check {target.name}: {obs.reason or 'not sure what is there'}",
                    expected_quantity=expected,
                    observed_quantity=observed,
                )
            )
        elif observed < expected:
            definite = True
            short = expected - observed
            discrepancies.append(
                Discrepancy(
                    **common,
                    kind="missing",
                    message=f"Missing: {short} {target.name}",
                    expected_quantity=expected,
                    observed_quantity=observed,
                    missing_quantity=short,
                )
            )
        elif observed > expected:
            definite = True
            discrepancies.append(
                Discrepancy(
                    **common,
                    kind="unexpected",
                    message=f"Extra: {observed - expected} {target.name}",
                    expected_quantity=expected,
                    observed_quantity=observed,
                )
            )
        if any(
            line.requires_manual_review for line in order.lines if line.line_id in target.line_ids
        ):
            discrepancies.append(
                Discrepancy(
                    **common,
                    kind="unsure",
                    message=f"Confirm the options and instructions for {target.name} manually.",
                )
            )

    for item in observations.unexpected_items:
        if item.item_id:
            definite = True  # confirmed as a known menu item that isn't on the ticket
            target = next(
                (target for target in targets if target.target_id == item.instead_of_target_id),
                None,
            )
            shortage = next(
                (
                    entry
                    for entry in discrepancies
                    if entry.target_id == item.instead_of_target_id and entry.kind == "missing"
                ),
                None,
            )
            paired = (
                target is not None
                and shortage is not None
                and item.quantity is not None
                and item.quantity <= shortage.missing_quantity
            )
            discrepancies.append(
                Discrepancy(
                    kind="wrong_item",
                    target_id=target.target_id if paired else None,
                    line_ids=target.line_ids if paired else [],
                    observed_quantity=item.quantity,
                    message=f"Wrong item: expected {target.name}; detected {item.name}"
                    if paired
                    else f"Wrong item: {item.name} is not on this ticket",
                )
            )
        else:
            discrepancies.append(
                Discrepancy(
                    kind="unidentified",
                    message=f"Unidentified item: {item.name}",
                    observed_quantity=item.quantity,
                )
            )

    if observations.scene_uncertainty and discrepancies:
        discrepancies.insert(
            0,
            Discrepancy(
                kind="unsure",
                line_ids=[line.line_id for line in order.lines],
                message=observations.scene_uncertainty,
            ),
        )
    if definite:
        verdict = "fail"
    elif discrepancies:
        verdict = "unsure"
    else:
        verdict = "pass"
    return Comparison(verdict=verdict, discrepancies=discrepancies)
