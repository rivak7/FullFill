import type { OrderState } from "../../api/generated/contracts";
import { toScreenState, type ScreenLine, type ScreenState } from "./screenState";
import "./station.css";

interface Props {
  state: OrderState;
  // Called when the worker accepts the amber items. Wire to StationApi.confirm later.
  onConfirm: (targetIds: string[]) => void;
}

export function StationScreen({ state, onConfirm }: Props) {
  const screen = toScreenState(state);
  return (
    <main className={`station tone-${screen.tone}`}>
      <Ticket orderId={state.order.order_id} lines={screen.lines} />
      <Status screen={screen} onConfirm={onConfirm} />
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

function Ticket({ orderId, lines }: { orderId: string; lines: ScreenLine[] }) {
  return (
    <section className="ticket" aria-label="Order ticket">
      <header className="ticket-header">
        <span className="ticket-label">Order</span>
        <span className="ticket-id">{orderId}</span>
      </header>
      <ul className="ticket-lines">
        {lines.map(({ line, status, note }) => (
          <li key={line.line_id} className={`ticket-line line-${status}`}>
            <span className="line-qty">{line.quantity}×</span>
            <span className="line-name">
              {line.name}
              {note && <span className="line-note">{note}</span>}
            </span>
            <span className="line-mark" aria-label={status}>
              {lineMarks[status]}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Status({ screen, onConfirm }: { screen: ScreenState; onConfirm: Props["onConfirm"] }) {
  const unsureTargets = screen.problems.flatMap((p) => (p.target_id ? [p.target_id] : []));
  return (
    <section className="status" aria-live="polite">
      <h1 className="status-headline">{screen.headline}</h1>
      {screen.detail && <p className="status-detail">{screen.detail}</p>}
      {screen.problems.length > 0 && (
        <ul className="status-problems">
          {screen.problems.map((p, i) => (
            <li key={p.target_id ?? i}>{p.message}</li>
          ))}
        </ul>
      )}
      {screen.tone === "amber" && (
        <button className="status-confirm" onClick={() => onConfirm(unsureTargets)}>
          Looks right, send it
        </button>
      )}
    </section>
  );
}
