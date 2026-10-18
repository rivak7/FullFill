import { useEffect, useState } from "react";
import { orderApi } from "../../api/client";
import type { OrderState } from "../../api/generated/contracts";
import { StationScreen } from "../station/StationScreen";

export function FulfillmentScreen() {
  const [orders, setOrders] = useState<OrderState[]>([]);
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(window.location.search).get("order"));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const snapshot = await orderApi.station(controller.signal);
        if (controller.signal.aborted) return;
        const incoming = snapshot.orders ?? [];
        setOrders(incoming);
        // Incoming orders join the queue without replacing the ticket a worker is handling.
        setSelected(current => incoming.some(state => state.order.order_id === current) ? current : incoming[0]?.order.order_id ?? null);
        setError(null);
      } catch (error) {
        if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Could not refresh orders.");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh]);

  function select(id: string) {
    setSelected(id);
    const url = new URL(window.location.href);
    url.searchParams.set("order", id);
    window.history.replaceState(null, "", url);
  }

  const current = orders.find(state => state.order.order_id === selected);
  return (
    <div className="fulfillment-page">
      <div className="queue-toolbar">
        <div><span className={`connection-dot ${error ? "offline" : loading ? "loading" : ""}`} /><strong>{error ? "Disconnected" : loading ? "Connecting…" : "Kitchen queue"}</strong>{!error && !loading && <span className="queue-count">{orders.length} open</span>}</div>
        <button onClick={() => setRefresh(value => value + 1)}>Refresh</button>
      </div>
      {error && <div className="connection-error" role="alert">{error}</div>}
      <div className="fulfillment-layout">
        <aside className="order-queue" aria-label="Incoming orders">
          <div className="queue-heading"><h2>Orders</h2></div>
          {!loading && !error && !orders.length && <p className="queue-empty">No open orders.</p>}
          {orders.map(state => <button className="queue-ticket" key={state.order.order_id} aria-pressed={state.order.order_id === selected} disabled={!!error} onClick={() => select(state.order.order_id)}>
            <span className="queue-ticket-top"><strong>#{state.order.order_id.slice(-8).toUpperCase()}</strong><span>{state.order.lines.reduce((sum, line) => sum + line.quantity, 0)} items</span></span>
            <span className="queue-ticket-items">{state.order.lines.map(line => `${line.quantity}× ${line.name}`).join(" · ")}</span>
            <span className="queue-ticket-status">{state.current_check ? "Check available" : "Not checked"}</span>
          </button>)}
        </aside>
        <div className="active-ticket">
          {error ? <div className="empty-state" role="status"><h1>Reconnecting…</h1></div>
            : loading ? <div className="empty-state" role="status"><h1>Loading orders…</h1></div>
            : current ? <><StationScreen state={current} /><p className="vision-note">Camera not connected</p></>
            : <div className="empty-state"><h1>{selected && orders.length ? "Choose an order" : "Waiting for orders"}</h1></div>}
        </div>
      </div>
    </div>
  );
}
