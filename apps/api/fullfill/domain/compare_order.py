"""Decision rules: turn an order plus vision observations into green / red / amber.

- pass (green): every target's count matches and nothing is uncertain.
- fail (red): a definite shortfall or excess. A red stays red even if something else is unsure.
- unsure (amber): something the worker should look at, such as a target the model couldn't
  see or tell apart, an unlabeled item that might be a labeled one, or an item that isn't
  on the ticket. The worker decides.
"""

from collections.abc import Mapping

from fullfill_contracts.checks import Comparison, Discrepancy
from fullfill_contracts.orders import MenuItem, OrderSnapshot
from fullfill_contracts.vision import Observations, VerificationTarget


def targets_for(
    order: OrderSnapshot, menu: Mapping[str, MenuItem] | None = None
) -> tuple[VerificationTarget, ...]:
    """One target per item, summing the quantities of lines for the same item."""
    grouped: dict[str, VerificationTarget] = {}
    for line in order.lines:
        existing = grouped.get(line.item_id)
        if existing is not None:
            grouped[line.item_id] = existing.model_copy(
                update={
                    "line_ids": [*existing.line_ids, line.line_id],
                    "expected_quantity": existing.expected_quantity + line.quantity,
                }
            )
            continue
        item = (menu or {}).get(line.item_id)
        mode = item.verification_mode if item else line.verification_mode
        grouped[line.item_id] = VerificationTarget(
            target_id=line.item_id,
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

    # A poor whole-scene view invalidates counts, including apparent shortages.
    # It must never turn missing evidence into a confident red or green result.
    if observations.scene_uncertainty:
        return Comparison(
            verdict="unsure",
            discrepancies=[
                Discrepancy(
                    kind="unsure",
                    line_ids=[line.line_id for line in order.lines],
                    message=observations.scene_uncertainty,
                )
            ],
        )

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

    for item in observations.unexpected_items:
        discrepancies.append(
            Discrepancy(kind="unexpected", message=f"Not on the ticket: {item.name}")
        )

    if definite:
        verdict = "fail"
    elif discrepancies:
        verdict = "unsure"
    else:
        verdict = "pass"
    return Comparison(verdict=verdict, discrepancies=discrepancies)
