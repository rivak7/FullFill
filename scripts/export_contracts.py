"""Export the Python boundary models for TypeScript generation; no app startup required."""

from pathlib import Path

from fullfill_contracts.captures import (
    CaptureMetadata,
    CaptureReceipt,
    CaptureRequest,
    CreateCaptureRequest,
)
from fullfill_contracts.checks import (
    CheckAccepted,
    CheckResult,
    Comparison,
    CreateCheckRequest,
    OverrideRequest,
)
from fullfill_contracts.common import Contract
from fullfill_contracts.events import StationEvent, StationSnapshot
from fullfill_contracts.notifications import DeliveryResult, Notification
from fullfill_contracts.orders import MenuItem, OrderSnapshot, ReferenceSet
from fullfill_contracts.vision import Observations, VerificationTarget


class FullFillContracts(Contract):
    """Schema bundle only, not an API request."""

    order: OrderSnapshot
    menu_item: MenuItem
    references: ReferenceSet
    capture_metadata: CaptureMetadata
    capture_receipt: CaptureReceipt
    capture_request: CaptureRequest
    create_capture_request: CreateCaptureRequest
    check_request: CreateCheckRequest
    check_accepted: CheckAccepted
    check_result: CheckResult
    comparison: Comparison
    override: OverrideRequest
    observations: Observations
    vision_target: VerificationTarget
    station_event: StationEvent
    station_snapshot: StationSnapshot
    notification: Notification
    delivery_result: DeliveryResult


if __name__ == "__main__":
    import json

    destination = (
        Path(__file__).resolve().parents[1] / "packages/contracts/generated/contracts.schema.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(FullFillContracts.model_json_schema(), indent=2, sort_keys=True) + "\n"
    )
