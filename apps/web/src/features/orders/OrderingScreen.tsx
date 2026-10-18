import { orderNumber } from "../../orderNumber";
import { useEffect, useRef, useState } from "react";
import { ApiError, orderApi, type CreateOrderInput, type MenuEntry } from "../../api/client";
import type { OrderSnapshot } from "../../api/generated/contracts";
import { siteScreen } from "../../site";

const storageKey = "fullfill.pending-order.v1";
type PendingOrder = { key: string; body: CreateOrderInput; menu?: MenuEntry[] };

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
  const [revision, setRevision] = useState("");
  const [needsReview, setNeedsReview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [menuError, setMenuError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [created, setCreated] = useState<OrderSnapshot | null>(null);
  const menuRef = useRef(menu);
  const quantitiesRef = useRef(quantities);
  const pendingRef = useRef(pending);
  menuRef.current = menu;
  quantitiesRef.current = quantities;
  pendingRef.current = pending;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = false;
    async function poll() {
      if (active || controller.signal.aborted) return;
      clearTimeout(timer);
      active = true;
      try {
        const data = await orderApi.menu(controller.signal);
        if (controller.signal.aborted) return;
        const old = menuRef.current;
        const affected = old.some(item => {
          if (!(quantitiesRef.current[item.item_id] > 0)) return false;
          const next = data.items.find(value => value.item_id === item.item_id);
          return !next || ["name", "price_cents", "available", "archived"].some(field => item[field as keyof MenuEntry] !== next[field as keyof MenuEntry]);
        });
        if (affected && !pendingRef.current) setNeedsReview(true);
        // Keep unavailable basket lines visible until the customer removes them.
        const missing = old.filter(item => quantitiesRef.current[item.item_id] > 0 && !data.items.some(next => next.item_id === item.item_id)).map(item => ({ ...item, available: false, archived: true }));
        setMenu([...data.items, ...missing]); setRevision(data.revision); setMenuError(null);
      } catch (error) {
        if (!controller.signal.aborted) setMenuError(error instanceof Error ? error.message : "Could not refresh menu.");
      } finally {
        active = false;
        if (!controller.signal.aborted) { setLoading(false); timer = setTimeout(poll, 5000); }
      }
    }
    const focus = () => { if (!document.hidden) void poll(); };
    void poll();
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", focus);
    return () => { controller.abort(); clearTimeout(timer); window.removeEventListener("focus", focus); document.removeEventListener("visibilitychange", focus); };
  }, [refresh]);

  const selected = (pending?.menu ?? menu).filter(item => (quantities[item.item_id] ?? 0) > 0);
  const total = selected.reduce((sum, item) => sum + item.price_cents * quantities[item.item_id], 0);
  const count = selected.reduce((sum, item) => sum + quantities[item.item_id], 0);
  const unavailable = selected.some(item => !item.available || item.archived);

  function adjust(id: string, amount: number) {
    if (pending || sending) return;
    setCreated(null);
    setError(null);
    setQuantities(values => ({ ...values, [id]: Math.max(0, Math.min(50, (values[id] ?? 0) + amount)) }));
  }

  async function submit() {
    if (sending || (!pending && !selected.length)) return;
    let attempt: PendingOrder = pending ?? {
      key: crypto.randomUUID(),
      body: { items: selected.map(item => ({ item_id: item.item_id, quantity: quantities[item.item_id] })), menu_revision: revision },
    };
    setSending(true);
    setError(null);
    setCreated(null);
    try {
      if (!attempt.body.quote) {
        const body = await orderApi.prepare(attempt.body, attempt.key);
        attempt = { ...attempt, body, menu: selected };
        // Persist the signed checkout before submission. Menu edits cannot reprice a retry.
        savePending(attempt); setPending(attempt);
      }
      const order = await orderApi.create(attempt.body, attempt.key);
      setCreated(order);
      setQuantities({});
      setPending(null);
      setNeedsReview(false);
      savePending(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not place this order.");
      if (!attempt.body.quote && error instanceof ApiError && [409, 422].includes(error.status)) {
        setNeedsReview(true);
        setRefresh(value => value + 1);
      }
    } finally { setSending(false); }
  }

  return (
    <main className="ordering-page">
      {created && <section className="success-banner" role="status">
        <strong>Order #{orderNumber(created.order_id)} sent</strong>
        {siteScreen === "combined" && <a href={`/fulfill?order=${encodeURIComponent(created.order_id)}`} target="_blank" rel="noreferrer">View ticket ↗</a>}
      </section>}
      <div className="ordering-layout">
        <section className="menu-section" aria-label="Menu">
          <div className="section-heading"><h1>Menu</h1><span className="menu-sync-label">{menuError ? "Sync interrupted" : "Updates automatically"}</span></div>
          {loading && <p role="status">Loading menu…</p>}
          {menuError && <div className="error-banner" role="alert">{menuError} <button onClick={() => setRefresh(value => value + 1)}>Retry</button></div>}
          {!loading && menu.filter(item => !item.archived).map(item => <article className={`menu-card ${!item.available ? "unavailable-item" : ""}`} key={item.item_id}>
            <div className="menu-copy"><h2>{item.name}</h2><span>{money(item.price_cents, item.currency)}</span></div>
            {!item.available ? <span className="availability sold-out">Sold out</span> : <div className="quantity-picker" role="group" aria-label={`${item.name} quantity`}>
              <button aria-label={`Remove one ${item.name}`} disabled={!!pending || sending || !quantities[item.item_id]} onClick={() => adjust(item.item_id, -1)}>−</button>
              <output aria-label={`${item.name} count`}>{quantities[item.item_id] ?? 0}</output>
              <button aria-label={`Add one ${item.name}`} disabled={!!pending || sending || quantities[item.item_id] >= 50} onClick={() => adjust(item.item_id, 1)}>+</button>
            </div>}
          </article>)}
          {!loading && !menuError && !menu.some(item => !item.archived) && <p className="menu-empty">The menu is being updated. Check back shortly.</p>}
        </section>
        <aside className="basket" aria-label="Your order">
          <h2>Your order</h2>
          {!count && <p className="basket-empty">Add items from the menu.</p>}
          <ul className="basket-lines">{selected.map(item => <li key={item.item_id}><span><b>{quantities[item.item_id]}×</b> {item.name}{(!item.available || item.archived) && !pending && <span className="basket-unavailable">Unavailable <button disabled={sending} onClick={() => setQuantities(values => ({ ...values, [item.item_id]: 0 }))}>Remove</button></span>}</span><span>{money(item.price_cents * quantities[item.item_id], item.currency)}</span></li>)}</ul>
          <div className="basket-total"><span>Total</span><strong>{money(total)}</strong></div>
          {error && <p className="error-banner" role="alert">{error}</p>}
          {needsReview && !pending && <div className="menu-review" role="status"><strong>The menu changed.</strong><p>Review the updated items and total.</p><button type="button" className="secondary-button" disabled={sending} onClick={() => { setNeedsReview(false); setError(null); }}>Use updated menu</button></div>}
          {unavailable && !pending && <p className="pending-note">Remove unavailable items to continue.</p>}
          {pending && !sending && <p className="pending-note">Order unconfirmed. Retry won’t create a duplicate.</p>}
          <button className="primary-button" onClick={submit} disabled={sending || (!pending && (!count || !!menuError || loading || unavailable || needsReview))}>
            {sending ? "Sending…" : pending ? "Retry order" : "Place order"}
          </button>
        </aside>
      </div>
    </main>
  );
}
