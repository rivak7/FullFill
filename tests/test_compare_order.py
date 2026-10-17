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
    assert result.discrepancies[0].message == "Not on the ticket: Celsius can"
