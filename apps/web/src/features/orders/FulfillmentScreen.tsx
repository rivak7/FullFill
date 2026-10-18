import { useEffect, useRef, useState } from "react";
import { ApiError, orderApi, type OrderStatusEdit } from "../../api/client";
import { StationScreen } from "../station/StationScreen";
import { toScreenState } from "../station/screenState";
import { isFulfilled, reconcileQueue, type QueueState } from "./queueState";

type StatusAttempt = { id: string; body: OrderStatusEdit; key: string };

const refreshDelayMs = 1000;
const initialRetryDelayMs = 3000;
const maxRetryDelayMs = 30000;

export function FulfillmentScreen() {
  const [queue, setQueue] = useState<QueueState>(() => ({ orders: [], selected: new URLSearchParams(window.location.search).get("order") }));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<StatusAttempt | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const epoch = useRef(0);
  const saving = useRef(false);
  const list = useRef<HTMLElement>(null);
  const { orders, selected } = queue;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let retryDelay = 0;
    async function poll() {
      const started = epoch.current;
      try {
        if (saving.current) return;
        const snapshot = await orderApi.station(controller.signal);
        if (controller.signal.aborted || started !== epoch.current) return;
        // The API keeps chronological order for cleanup; display newest at top.
        setQueue(previous => reconcileQueue(previous, [...(snapshot.orders ?? [])].reverse()));
        setError(null);
        retryDelay = 0;
      } catch (error) {
        if (!controller.signal.aborted && started === epoch.current) {
          setError(error instanceof Error ? error.message : "Could not refresh orders.");
          retryDelay = Math.min(retryDelay ? retryDelay * 2 : initialRetryDelayMs, maxRetryDelayMs);
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          // Wait until this request finishes so slow responses never pile up.
          timer = setTimeout(poll, retryDelay || refreshDelayMs);
        }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh]);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (selected) url.searchParams.set("order", selected);
    else url.searchParams.delete("order");
    window.history.replaceState(null, "", url);
    list.current?.querySelector('[aria-pressed="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [selected, loading]);

  async function submit(attempt: StatusAttempt) {
    if (saving.current) return;
    saving.current = true; epoch.current++;
    setPending(attempt); setBusy(true); setActionError(null); setNotice("");
    try {
      const updated = await orderApi.setStatus(attempt.id, attempt.body, attempt.key);
      setQueue(previous => reconcileQueue(previous, previous.orders.map(state => state.order.order_id === attempt.id ? updated : state)));
      setPending(null);
      setNotice(`#${attempt.id.slice(-8).toUpperCase()} · ${toScreenState(updated).headline}`);
    } catch (error) {
      if (error instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(error.status)) setPending(null);
      setActionError(error instanceof Error ? error.message : "Could not save the order status.");
    } finally {
      saving.current = false; setBusy(false); setRefresh(value => value + 1);
    }
  }

  const current = orders.find(state => state.order.order_id === selected);
  const currentTone = current ? toScreenState(current).tone : null;
  const waiting = orders.filter(state => !isFulfilled(state)).length;
  const locked = busy || !!pending || !!error;

  function updateStatus(status: OrderStatusEdit["status"]) {
    if (!current || locked) return;
    void submit({ id: current.order.order_id, body: { status, expected_revision: current.order.revision }, key: crypto.randomUUID() });
  }

  return (
    <div className="fulfillment-page">
      <div className="queue-toolbar">
        <div><span className={`connection-dot ${error ? "offline" : loading ? "loading" : ""}`} /><strong>{error ? "Disconnected" : loading ? "Connecting…" : "Kitchen queue"}</strong>{!error && !loading && <span className="queue-count">{waiting} to do · {orders.length - waiting} fulfilled</span>}</div>
        <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>Refresh</button>
      </div>
      {error && <div className="connection-error" role="alert">{error}</div>}
      {actionError && <div className="connection-error" role="alert">{actionError}{pending && <button className="secondary-button" disabled={busy} onClick={() => void submit(pending)}>{busy ? "Saving…" : "Retry status"}</button>}</div>}
      <div className="queue-announcement" role="status">{notice}</div>
      <div className="fulfillment-layout">
        <aside ref={list} className="order-queue" aria-label="Incoming orders" tabIndex={0}>
          <div className="queue-heading"><h2>Orders</h2><span>Newest first</span></div>
          {!loading && !error && !orders.length && <p className="queue-empty">No orders yet.</p>}
          {orders.map(state => {
            const screen = toScreenState(state);
            const itemCount = state.order.lines.reduce((sum, line) => sum + line.quantity, 0);
            return <button className={`queue-ticket queue-${screen.tone}`} key={state.order.order_id} aria-pressed={state.order.order_id === selected} disabled={locked} onClick={() => { setQueue(previous => ({ ...previous, selected: state.order.order_id })); setActionError(null); }}>
              <span className="queue-ticket-top"><strong>#{state.order.order_id.slice(-8).toUpperCase()}</strong><span>{itemCount} {itemCount === 1 ? "item" : "items"}</span></span>
              <span className="queue-ticket-items">{state.order.lines.map(line => `${line.quantity}× ${line.name}`).join(" · ")}</span>
              <span className="queue-ticket-status">{screen.tone === "green" ? "✓ " : screen.tone === "amber" ? "? " : "○ "}{screen.headline}</span>
            </button>;
          })}
        </aside>
        <div className="active-ticket">
          {error ? <div className="empty-state" role="status"><h1>Reconnecting…</h1></div>
            : loading ? <div className="empty-state" role="status"><h1>Loading orders…</h1></div>
            : current ? <>
              <StationScreen state={current} />
              <div className="fulfillment-actions" aria-label="Order status">
                <span>Manual check</span>
                {currentTone !== "red" && <button className="secondary-button" disabled={locked} onClick={() => updateStatus("unfulfilled")}>Reopen</button>}
                {currentTone !== "amber" && <button className="review-button" disabled={locked} onClick={() => updateStatus("unsure")}>Needs review</button>}
                {currentTone !== "green" && <button className="primary-button" disabled={locked} onClick={() => updateStatus("fulfilled")}>{busy ? "Saving…" : "Fulfill order"}</button>}
              </div>
            </>
            : <div className="empty-state"><h1>{waiting ? "No newer orders" : orders.length ? "All caught up" : "Waiting for orders"}</h1>{!!waiting && <p>Select another ticket to continue.</p>}</div>}
        </div>
      </div>
    </div>
  );
}
