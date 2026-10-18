// The one place that turns an order's check result into what the station shows.
// Everything else on the screen reads from ScreenState, never from the raw contract.
import type { Discrepancy, OrderLine, OrderState } from "../../api/generated/contracts";

export type Tone = "waiting" | "checking" | "green" | "red" | "amber" | "error";

export type LineStatus = "unchecked" | "ok" | "accepted" | "missing" | "unsure";

export interface ScreenLine {
  line: OrderLine;
  status: LineStatus;
  note: string | null;
}

export interface ScreenState {
  tone: Tone;
  headline: string;
  detail: string | null;
  lines: ScreenLine[];
  // Things the worker should look at: missing items for red, unsure items for amber.
  problems: Discrepancy[];
  confirmedByStaff: boolean;
}

export function toScreenState(state: OrderState): ScreenState {
  const candidate = state.current_check ?? null;
  const check = candidate?.order_id === state.order.order_id && candidate.order_revision === state.order.revision ? candidate : null;
  const discrepancies = check?.discrepancies ?? [];
  const checked = check?.execution_status === "completed" && !!check.verdict;
  const lines = state.order.lines.map((line) => toScreenLine(line, checked ? discrepancies : null));

  if (state.disposition === "overridden") {
    // A manual fulfillment confirms the whole ticket, including unchecked items.
    const accepted = lines.map((l) =>
      l.status !== "ok" ? { ...l, status: "accepted" as const, note: "Confirmed by staff" } : l,
    );
    return { tone: "green", headline: "Fulfilled", detail: "Confirmed by staff", lines: accepted, problems: [], confirmedByStaff: true };
  }
  if (state.disposition === "needs_review" && !check) {
    return { tone: "amber", headline: "Needs review", detail: null, lines, problems: [], confirmedByStaff: false };
  }
  if (candidate && !check) {
    return { tone: "amber", headline: "Needs review", detail: "Ticket changed. Check this order again.", lines, problems: [], confirmedByStaff: false };
  }
  if (!check) {
    return { tone: "red", headline: "Unfulfilled", detail: null, lines, problems: [], confirmedByStaff: false };
  }
  if (check.execution_status === "failed") {
    return {
      tone: "amber",
      headline: "Needs review",
      detail: "Camera check failed. Check manually or take a new photo.",
      lines,
      problems: [],
      confirmedByStaff: false,
    };
  }
  if (check.execution_status !== "completed") {
    return { tone: "checking", headline: "Checking…", detail: null, lines, problems: [], confirmedByStaff: false };
  }

  const isUnsure = (d: Discrepancy) => d.kind === "unsure" || (d.kind === "unexpected" && d.expected_quantity == null);
  const definite = discrepancies.filter((d) => !isUnsure(d));
  const unsure = discrepancies.filter(isUnsure);

  if (check.verdict === "fail" || definite.length > 0) {
    return { tone: "red", headline: "Unfulfilled", detail: "Camera found a mismatch", lines, problems: discrepancies, confirmedByStaff: false };
  }
  if (check.verdict !== "pass" || unsure.length > 0) {
    return {
      tone: "amber",
      headline: "Needs review",
      detail: unsure.length ? null : "No reliable result. Check manually or take a new photo.",
      lines,
      problems: unsure,
      confirmedByStaff: false,
    };
  }
  return { tone: "green", headline: "Fulfilled", detail: "Camera match", lines, problems: [], confirmedByStaff: false };
}

function toScreenLine(line: OrderLine, discrepancies: Discrepancy[] | null): ScreenLine {
  if (discrepancies === null) return { line, status: "unchecked", note: null };
  const hit = discrepancies.find((d) => d.line_ids?.includes(line.line_id));
  if (!hit) return { line, status: "ok", note: null };
  if (hit.kind === "unsure") return { line, status: "unsure", note: hit.message };
  return { line, status: "missing", note: hit.message };
}
