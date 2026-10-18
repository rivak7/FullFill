import pytest
from fullfill.domain.compare_order import compare_order, targets_for
from fullfill_contracts.orders import MenuItem, OrderLine, OrderSnapshot
from fullfill_contracts.vision import Observations, TargetObservation, UnexpectedItem

ORDER = OrderSnapshot(
    order_id="o1",
    revision=1,
    lines=[
        OrderLine(line_id="l1", item_id="chicken_burrito", name="Chicken burrito", quantity=1),
        OrderLine(line_id="l2", item_id="ketchup", name="Ketchup packet", quantity=2),
        OrderLine(line_id="l3", item_id="ketchup", name="Ketchup packet", quantity=1),
    ],
)


def seen(chicken=("present", 1), ketchup=("present", 3), unexpected=()):
    return Observations(
        capture_id="c1",
        targets=[
            TargetObservation(
                target_id="chicken_burrito", status=chicken[0], observed_quantity=chicken[1]
            ),
            TargetObservation(target_id="ketchup", status=ketchup[0], observed_quantity=ketchup[1]),
        ],
        unexpected_items=[UnexpectedItem(name=n) for n in unexpected],
    )


def test_lines_for_the_same_item_are_one_target():
    menu = {
        "chicken_burrito": MenuItem(
            item_id="chicken_burrito",
            name="Chicken burrito",
            verification_mode="label",
            label_aliases=["C"],
        )
    }
    targets = {t.target_id: t for t in targets_for(ORDER, menu)}
    assert targets["ketchup"].expected_quantity == 3
    assert targets["ketchup"].line_ids == ["l2", "l3"]
    assert targets["chicken_burrito"].verification_mode == "label"
    assert targets["chicken_burrito"].label_aliases == ["C"]


def test_exact_counts_pass():
    assert compare_order(ORDER, seen()).verdict == "pass"


def test_variant_targets_do_not_merge_and_ids_survive_line_reordering():
    lines = [
        OrderLine(line_id="regular", item_id="burger", name="Burger", quantity=1),
        OrderLine(
            line_id="custom",
            item_id="burger",
            name="Burger — no cheese",
            quantity=1,
            requires_manual_review=True,
        ),
        OrderLine(line_id="another", item_id="burger", name="Burger", quantity=2),
    ]
    order = OrderSnapshot(order_id="variants", revision=1, lines=lines)
    targets = targets_for(order)
    assert [(t.name, t.expected_quantity) for t in targets] == [
        ("Burger", 3),
        ("Burger — no cheese", 1),
    ]
    reversed_targets = targets_for(order.model_copy(update={"lines": list(reversed(lines))}))
    assert {t.name: t.target_id for t in targets} == {t.name: t.target_id for t in reversed_targets}
    observations = Observations(
        capture_id="photo",
        targets=[
            TargetObservation(
                target_id=t.target_id, status="present", observed_quantity=t.expected_quantity
            )
            for t in targets
        ],
    )
    comparison = compare_order(order, observations)
    assert comparison.verdict == "unsure"
    assert comparison.discrepancies[0].line_ids == ["custom"]


def test_missing_item_fails_and_names_it():
    result = compare_order(ORDER, seen(ketchup=("present", 2)))
    assert result.verdict == "fail"
    assert result.discrepancies[0].message == "Missing: 1 Ketchup packet"
    assert result.discrepancies[0].missing_quantity == 1


def test_extra_item_fails():
    assert compare_order(ORDER, seen(ketchup=("present", 4))).verdict == "fail"


def test_unsure_target_is_amber_even_with_zero_count():
    # An unlabeled burrito: the model can't confirm chicken, so the worker decides.
    result = compare_order(ORDER, seen(chicken=("unsure", 0)))
    assert result.verdict == "unsure"
    assert result.discrepancies[0].kind == "unsure"


def test_red_wins_over_amber():
    result = compare_order(ORDER, seen(chicken=("unsure", None), ketchup=("missing", 0)))
    assert result.verdict == "fail"
    assert {d.kind for d in result.discrepancies} == {"unsure", "missing"}


def test_item_not_on_the_ticket_is_amber():
    result = compare_order(ORDER, seen(unexpected=["Celsius can"]))
    assert result.verdict == "unsure"
    assert result.discrepancies[0].message == "Unidentified item: Celsius can"


def test_scene_note_alone_does_not_block_an_exact_match():
    # Every ticket item counted exactly and nothing else seen: the order is complete.
    observations = seen().model_copy(update={"scene_uncertainty": "Open the closed bag."})
    result = compare_order(ORDER, observations)
    assert result.verdict == "pass"
    assert result.discrepancies == []


def test_scene_note_is_shown_with_other_doubts():
    observations = seen(ketchup=("unsure", None)).model_copy(
        update={"scene_uncertainty": "Open the closed bag."}
    )
    result = compare_order(ORDER, observations)
    assert result.verdict == "unsure"
    assert result.discrepancies[0].message == "Open the closed bag."
    assert result.discrepancies[0].line_ids == ["l1", "l2", "l3"]


def test_red_wins_over_a_poor_scene_view():
    observations = seen(ketchup=("missing", 0)).model_copy(
        update={"scene_uncertainty": "Open the closed bag."}
    )
    result = compare_order(ORDER, observations)
    assert result.verdict == "fail"
    assert {d.kind for d in result.discrepancies} == {"unsure", "missing"}


def test_duplicate_observations_do_not_silently_replace_each_other():
    observations = seen()
    observations.targets.append(observations.targets[0])
    with pytest.raises(ValueError):
        compare_order(ORDER, observations)


def test_known_substitute_shows_both_missing_and_wrong_items():
    observed = seen(chicken=("missing", 0))
    observed.unexpected_items = [
        UnexpectedItem(
            name="Beef burrito", item_id="beef", instead_of_target_id="chicken_burrito", quantity=1
        )
    ]
    result = compare_order(ORDER, observed)
    assert result.verdict == "fail"
    assert [issue.kind for issue in result.discrepancies] == ["missing", "wrong_item"]
    wrong = result.discrepancies[1]
    assert wrong.message == "Wrong item: expected Chicken burrito; detected Beef burrito"
    assert wrong.line_ids == ["l1"]


def test_unknown_extra_is_not_forced_into_a_menu_identity_or_substitution():
    observed = seen()
    observed.unexpected_items = [UnexpectedItem(name="Covered container", quantity=1)]
    result = compare_order(ORDER, observed)
    assert result.verdict == "unsure"
    assert result.discrepancies[0].kind == "unidentified"
    assert result.discrepancies[0].target_id is None


def test_extra_is_not_paired_to_an_item_that_is_not_missing():
    observed = seen()
    observed.unexpected_items = [
        UnexpectedItem(
            name="Beef burrito", item_id="beef", instead_of_target_id="chicken_burrito", quantity=1
        )
    ]
    result = compare_order(ORDER, observed)
    assert result.verdict == "fail"
    assert result.discrepancies[0].target_id is None
    assert result.discrepancies[0].message == "Wrong item: Beef burrito is not on this ticket"
