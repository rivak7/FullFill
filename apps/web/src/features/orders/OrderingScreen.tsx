import { useEffect, useState } from "react";
import { ApiError, orderApi, type CreateOrderInput, type MenuEntry } from "../../api/client";
import type { OrderSnapshot } from "../../api/generated/contracts";

const storageKey = "fullfill.pending-order.v1";
type PendingOrder = { key: string; body: CreateOrderInput };

function readPending(): PendingOrder | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    return typeof value?.key === "string" && Array.isArray(value?.body?.items) ? value : null;
  } catch { return null; }
}

function savePending(value: PendingOrder | null) {
  try {
    if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
    else sessionStorage.removeItem(storageKey);
  } catch { /* Retain the same key in component state if browser storage is unavailable. */ }
}

const money = (cents: number, currency = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);

export function OrderingScreen() {
  const [pending, setPending] = useState<PendingOrder | null>(readPending);
  const [quantities, setQuantities] = useState<Record<string, number>>(() =>
    Object.fromEntries((readPending()?.body.items ?? []).map(item => [item.item_id, item.quantity])),
  );
  const [menu, setMenu] = useState<MenuEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [menuError, setMenuError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [created, setCreated] = useState<OrderSnapshot | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    orderApi.menu(controller.signal).then(data => {
      if (!controller.signal.aborted) { setMenu(data); setMenuError(null); }
    }).catch(error => {
      if (!controller.signal.aborted) setMenuError(error.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  const selected = menu.filter(item => (quantities[item.item_id] ?? 0) > 0);
  const total = selected.reduce((sum, item) => sum + item.price_cents * quantities[item.item_id], 0);
  const count = selected.reduce((sum, item) => sum + quantities[item.item_id], 0);

  function adjust(id: string, amount: number) {
    if (pending || sending) return;
    setCreated(null);
    setError(null);
    setQuantities(values => ({ ...values, [id]: Math.max(0, Math.min(50, (values[id] ?? 0) + amount)) }));
  }

  async function submit() {
    if (sending || (!pending && !selected.length)) return;
    const attempt = pending ?? {
      key: crypto.randomUUID(),
      body: { items: selected.map(item => ({ item_id: item.item_id, quantity: quantities[item.item_id] })) },
    };
    // Keep this exact request/key after a timeout, including across page reloads.
    savePending(attempt);
    setPending(attempt);
    setSending(true);
    setError(null);
    setCreated(null);
    try {
      const order = await orderApi.create(attempt.body, attempt.key);
      setCreated(order);
      setQuantities({});
      setPending(null);
      savePending(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not place this order.");
      // Validation rejects before contacting Square, so it is safe to edit the basket.
      if (error instanceof ApiError && error.status === 422) {
        setPending(null);
        savePending(null);
      }
    } finally { setSending(false); }
  }

  return (
    <main className="ordering-page">
      {created && <section className="success-banner" role="status">
        <strong>Order #{created.order_id.slice(-8).toUpperCase()} sent</strong>
        <a href={`/fulfill?order=${encodeURIComponent(created.order_id)}`} target="_blank" rel="noreferrer">View ticket ↗</a>
      </section>}
      <div className="ordering-layout">
        <section className="menu-section" aria-label="Menu">
          <div className="section-heading"><h1>Menu</h1></div>
          {loading && <p role="status">Loading menu…</p>}
          {menuError && <div className="error-banner" role="alert">{menuError} <button onClick={() => setRefresh(value => value + 1)}>Retry</button></div>}
          {!loading && !menuError && menu.map(item => <article className="menu-card" key={item.item_id}>
            <div className="menu-copy"><h2>{item.name}</h2><span>{money(item.price_cents, item.currency)}</span></div>
            <div className="quantity-picker" role="group" aria-label={`${item.name} quantity`}>
              <button aria-label={`Remove one ${item.name}`} disabled={!!pending || sending || !quantities[item.item_id]} onClick={() => adjust(item.item_id, -1)}>−</button>
              <output aria-label={`${item.name} count`}>{quantities[item.item_id] ?? 0}</output>
              <button aria-label={`Add one ${item.name}`} disabled={!!pending || sending || quantities[item.item_id] >= 50} onClick={() => adjust(item.item_id, 1)}>+</button>
            </div>
          </article>)}
        </section>
        <aside className="basket" aria-label="Your order">
          <h2>Your order</h2>
          {!count && <p className="basket-empty">Add items from the menu.</p>}
          <ul className="basket-lines">{selected.map(item => <li key={item.item_id}><span><b>{quantities[item.item_id]}×</b> {item.name}</span><span>{money(item.price_cents * quantities[item.item_id], item.currency)}</span></li>)}</ul>
          <div className="basket-total"><span>Total</span><strong>{money(total)}</strong></div>
          {error && <p className="error-banner" role="alert">{error}</p>}
          {pending && !sending && <p className="pending-note">Order unconfirmed. Retry won’t create a duplicate.</p>}
          <button className="primary-button" onClick={submit} disabled={sending || (!pending && (!count || !!menuError || loading))}>
            {sending ? "Sending…" : pending ? "Retry order" : "Place order"}
          </button>
        </aside>
      </div>
    </main>
  );
}
