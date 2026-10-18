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
  // An amber screen always has a detail or a problem that says why.
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
    return { tone: "amber", headline: "Needs review", detail: "Marked for review by staff.", lines, problems: [], confirmedByStaff: false };
  }
  if (candidate && !check) {
    return { tone: "amber", headline: "Needs review", detail: "Ticket changed. Check this order again.", lines, problems: [], confirmedByStaff: false };
  }
  if (!check) {
    return { tone: "red", headline: "Unfulfilled", detail: "Not checked yet", lines, problems: [], confirmedByStaff: false };
  }
  if (check.execution_status === "failed" || check.execution_status === "superseded") {
    return {
      tone: "amber",
      headline: check.execution_status === "failed" ? "Check failed" : "Needs review",
      detail: check.error_code === "reference_changed" ? "Menu reference photos changed. Check this order again." : check.execution_status === "superseded" ? "The camera view changed or confirmation expired. Take a new photo." : "Camera check failed. Check manually or take a new photo.",
      lines,
      problems: [],
      confirmedByStaff: false,
    };
  }
  if (check.execution_status !== "completed") {
    return { tone: "checking", headline: "Checking…", detail: null, lines, problems: [], confirmedByStaff: false };
  }

  // The backend's verdict is the only rule (apps/api/fullfill/domain/compare_order.py).
  if (check.verdict === "fail") {
    return { tone: "red", headline: "Unfulfilled", detail: "Doesn't match the ticket", lines, problems: discrepancies, confirmedByStaff: false };
  }
  if (check.verdict !== "pass") {
    return {
      tone: "amber",
      headline: "Needs review",
      // Amber always says why FullFill is unsure: each problem names an item, or this detail stands in.
      detail: discrepancies.length ? null : "No reliable result. Check manually or take a new photo.",
      lines,
      problems: discrepancies,
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

// One line for the queue: why an amber ticket needs a look.
export function amberReason(screen: ScreenState): string | null {
  if (screen.tone !== "amber") return null;
  const [first, ...rest] = screen.problems;
  if (!first) return screen.detail;
  return rest.length ? `${first.message} (+${rest.length} more)` : first.message;
}
