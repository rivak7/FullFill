import { orderNumber } from "../../orderNumber";
import type { OrderState } from "../../api/generated/contracts";
import { toScreenState, type ScreenLine, type ScreenState, type Tone } from "./screenState";
import "./station.css";

interface Props {
  state: OrderState;
}

// Display only: the worker never taps anything here.
export function StationScreen({ state }: Props) {
  const screen = toScreenState(state);
  return (
    <main className={`station tone-${screen.tone}`}>
      <Ticket orderId={state.order.order_id} lines={screen.lines} />
      <Status screen={screen} />
    </main>
  );
}

const lineMarks: Record<ScreenLine["status"], string> = {
  unchecked: "",
  ok: "✓",
  accepted: "✓",
  missing: "✗",
  unsure: "?",
};

export const toneMarks: Record<Tone, string> = {
  waiting: "…",
  checking: "…",
  green: "✓",
  red: "✗",
  amber: "?",
  error: "!",
};

function Ticket({ orderId, lines }: { orderId: string; lines: ScreenLine[] }) {
  return (
    <section className="ticket" aria-label="Order ticket">
      <header className="ticket-header">
        <span className="ticket-id" title={orderId}>#{orderNumber(orderId)}</span>
      </header>
      <ul className="ticket-lines">
        {lines.map(({ line, status }) => (
          <li key={line.line_id} className={`ticket-line line-${status}`}>
            <span className="line-qty">{line.quantity}</span>
            <span className="line-name">{line.name}</span>
            <span className="line-mark" aria-label={status}>
              {lineMarks[status]}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// The ticket marks which lines are off; this panel says why, once.
function Status({ screen }: { screen: ScreenState }) {
  return (
    <section className="status" aria-live="polite">
      <Face tone={screen.tone} />
      <h1 className="status-headline">{screen.headline}</h1>
      {screen.problems.length > 0 ? (
        <ul className="status-problems">
          {screen.problems.map((p, i) => (
            <li key={`${p.target_id ?? "scene"}:${p.kind}:${i}`}>{p.message}</li>
          ))}
        </ul>
      ) : screen.detail && <p className="status-detail">{screen.detail}</p>}
    </section>
  );
}

// The logo's face: happy when it matches, unsure for amber, sad when something's off.
function Face({ tone }: { tone: Tone }) {
  const mouth = tone === "green" ? "M14 30 Q24 42 34 30" : tone === "red" || tone === "error" ? "M15 37 Q24 28 33 37" : tone === "amber" ? "M16 34 Q20 31 24 34 T32 34" : "M17 34 L31 34";
  return (
    <svg className="status-face" viewBox="0 0 48 48" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="16" cy="18" r="2.6" fill="currentColor" stroke="none" />
      {tone === "green" ? <path d="M29 20 Q32 14 35 20" /> : <circle cx="32" cy="18" r="2.6" fill="currentColor" stroke="none" />}
      <path d={mouth} />
    </svg>
  );
}
