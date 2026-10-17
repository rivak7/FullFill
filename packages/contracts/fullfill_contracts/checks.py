"""Requests and outcomes; API workflow and decision rules are not implemented here."""

from typing import Literal

from pydantic import AwareDatetime, Field

from .common import Contract, Identifier, PositiveQuantity, Quantity, Revision

ExecutionStatus = Literal["queued", "running", "completed", "failed", "superseded"]
Verdict = Literal["pass", "fail", "unsure"]
Disposition = Literal["pending", "verified", "needs_review", "overridden"]


class CreateCheckRequest(Contract):
    schema_version: Literal[1] = 1
    station_id: Identifier
    order_id: Identifier
    order_revision: Revision
    expected_disposition_revision: Revision
    capture_id: Identifier


class CheckAccepted(Contract):
    check_id: Identifier
    execution_status: Literal["queued"] = "queued"
    disposition_revision: Revision


class Discrepancy(Contract):
    target_id: str | None = None
    line_ids: list[Identifier] = Field(default_factory=list)
    kind: Literal["missing", "unexpected", "unsure"]
    message: str
    expected_quantity: PositiveQuantity | None = None
    observed_quantity: Quantity | None = None
    missing_quantity: PositiveQuantity | None = None


class Comparison(Contract):
    verdict: Verdict
    discrepancies: list[Discrepancy] = Field(default_factory=list)


class CheckResult(Contract):
    schema_version: Literal[1] = 1
    check_id: Identifier
    capture_id: Identifier
    order_id: Identifier
    order_revision: Revision
    execution_status: ExecutionStatus
    verdict: Verdict | None = None
    disposition: Disposition
    disposition_revision: Revision
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    completed_at: AwareDatetime | None = None
    error_code: str | None = None


class OverrideRequest(Contract):
    check_id: Identifier
    order_revision: Revision
    expected_disposition_revision: Revision
    confirmed_target_ids: list[Identifier] = Field(default_factory=list)
    operator_reference: Identifier
    reason_code: Literal["worker_confirmed_present", "manual_order_acceptance"]
