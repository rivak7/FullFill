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
  const check = state.current_check ?? null;
  const discrepancies = check?.discrepancies ?? [];
  const checked = check?.execution_status === "completed";
  const lines = state.order.lines.map((line) => toScreenLine(line, checked ? discrepancies : null));

  if (state.disposition === "overridden") {
    // Staff accepted the uncertain items; show them as accepted, not machine-verified.
    const accepted = lines.map((l) =>
      l.status === "unsure" ? { ...l, status: "accepted" as const, note: "Confirmed by staff" } : l,
    );
    return { tone: "green", headline: "Order fulfilled", detail: "Confirmed by staff", lines: accepted, problems: [], confirmedByStaff: true };
  }
  if (!check) {
    return { tone: "waiting", headline: "Lay out the order", detail: "Place every item on the mat", lines, problems: [], confirmedByStaff: false };
  }
  if (check.execution_status === "failed") {
    return {
      tone: "error",
      headline: "Couldn't check this order",
      detail: "The camera check failed. Check the order by hand or try again.",
      lines,
      problems: [],
      confirmedByStaff: false,
    };
  }
  if (check.execution_status !== "completed") {
    return { tone: "checking", headline: "Checking…", detail: null, lines, problems: [], confirmedByStaff: false };
  }

  const definite = discrepancies.filter((d) => d.kind !== "unsure");
  const unsure = discrepancies.filter((d) => d.kind === "unsure");

  if (check.verdict === "fail" || definite.length > 0) {
    return { tone: "red", headline: "Order unfulfilled", detail: null, lines, problems: definite, confirmedByStaff: false };
  }
  if (check.verdict === "unsure" || unsure.length > 0) {
    return {
      tone: "amber",
      headline: "Needs a quick look",
      detail: "The camera isn't sure. You make the call.",
      lines,
      problems: unsure,
      confirmedByStaff: false,
    };
  }
  return { tone: "green", headline: "Order fulfilled", detail: null, lines, problems: [], confirmedByStaff: false };
}

function toScreenLine(line: OrderLine, discrepancies: Discrepancy[] | null): ScreenLine {
  if (discrepancies === null) return { line, status: "unchecked", note: null };
  const hit = discrepancies.find((d) => d.line_ids?.includes(line.line_id));
  if (!hit) return { line, status: "ok", note: null };
  if (hit.kind === "unsure") return { line, status: "unsure", note: hit.message };
  return { line, status: "missing", note: hit.message };
}
