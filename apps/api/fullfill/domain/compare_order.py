"""Decision-rule entry point, intentionally unimplemented."""

from fullfill_contracts.checks import Comparison
from fullfill_contracts.orders import OrderSnapshot
from fullfill_contracts.vision import Observations


def compare_order(order: OrderSnapshot, observations: Observations) -> Comparison:
    """Validate/aggregate the checklist without performing I/O."""
    raise NotImplementedError("Implement the main plan's checklist and uncertainty rules here.")
