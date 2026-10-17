// Hardcoded results for building and demoing the screen before the backend is wired up.
// Each scenario is a full OrderState, the same shape the API will send.
import type { CheckResult, Discrepancy, OrderLine, OrderState } from "../../api/generated/contracts";

const lines: OrderLine[] = [
  { line_id: "l1", item_id: "chicken_burrito", name: "Chicken burrito", quantity: 1, verification_mode: "label" },
  { line_id: "l2", item_id: "steak_burrito", name: "Steak burrito", quantity: 1, verification_mode: "label" },
  { line_id: "l3", item_id: "ketchup", name: "Ketchup packet", quantity: 3 },
  { line_id: "l4", item_id: "mayo", name: "Mayo packet", quantity: 2 },
  { line_id: "l5", item_id: "celsius", name: "Celsius can", quantity: 1 },
];

function order(check: CheckResult | null, disposition: OrderState["disposition"] = "pending"): OrderState {
  return {
    order: { order_id: "A-1042", revision: 1, lines: lines as OrderState["order"]["lines"] },
    disposition,
    disposition_revision: 1,
    current_check: check,
  };
}

function check(
  execution_status: CheckResult["execution_status"],
  verdict: CheckResult["verdict"],
  discrepancies: Discrepancy[] = [],
): CheckResult {
  return {
    check_id: "check_1",
    capture_id: "capture_1",
    order_id: "A-1042",
    order_revision: 1,
    execution_status,
    verdict,
    disposition: verdict === "pass" ? "verified" : verdict ? "needs_review" : "pending",
    disposition_revision: 2,
    discrepancies,
  };
}

export const scenarios: Record<string, { label: string; state: OrderState }> = {
  waiting: { label: "Waiting", state: order(null) },
  checking: { label: "Checking", state: order(check("running", null)) },
  green: { label: "Fulfilled", state: order(check("completed", "pass"), "verified") },
  red: {
    label: "Missing items",
    state: order(
      check("completed", "fail", [
        {
          kind: "missing",
          target_id: "t_ketchup",
          line_ids: ["l3"],
          message: "Missing: 1 ketchup packet",
          expected_quantity: 3,
          observed_quantity: 2,
          missing_quantity: 1,
        },
        { kind: "missing", target_id: "t_celsius", line_ids: ["l5"], message: "Missing: Celsius can", expected_quantity: 1, observed_quantity: 0, missing_quantity: 1 },
      ]),
      "needs_review",
    ),
  },
  amber: {
    label: "Unlabeled burrito",
    state: order(
      check("completed", "unsure", [
        {
          kind: "unsure",
          target_id: "t_steak",
          line_ids: ["l2"],
          message: "One burrito has no C/S label. Is it the steak burrito?",
        },
      ]),
      "needs_review",
    ),
  },
  error: { label: "Check failed", state: order(check("failed", null)) },
};
