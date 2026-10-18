import { learnOrderNumbers, orderNumber } from "../../orderNumber";
import { useEffect, useRef, useState } from "react";
import { ApiError, orderApi, type OrderStatusEdit } from "../../api/client";
import { StationScreen } from "../station/StationScreen";
import { amberReason, toScreenState } from "../station/screenState";
import { advancePastHeld, heldByOther, ownedBy, isFulfilled, reconcileQueue, type QueueState } from "./queueState";
import { CameraCheckPanel } from "./CameraCheckPanel";
import { StartFreshButton } from "./StartFreshButton";

type StatusAttempt = { id: string; body: OrderStatusEdit; key: string; restoreSelection?: boolean };
type Undo = { id: string; revision: number; expires: number };

const refreshDelayMs = 1000;
const initialRetryDelayMs = 3000;
const maxRetryDelayMs = 30000;

export function FulfillmentScreen() {
  const [workerId] = useState(() => crypto.randomUUID());
  const [queue, setQueue] = useState<QueueState>(() => ({ orders: [], selected: new URLSearchParams(window.location.search).get("order") }));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<StatusAttempt | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [undo, setUndo] = useState<Undo | null>(null);
  const [cameraPause, setCameraPause] = useState(0);
  const [checkNow, setCheckNow] = useState(0);
  // The order the camera just passed stays on screen while it is bagged.
  const bagging = useRef<string | null>(null);
  const epoch = useRef(0);
  const saving = useRef(false);
  const list = useRef<HTMLElement>(null);
  const { orders, selected } = queue;
  const latestQueue = useRef(queue); latestQueue.current = queue;

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
        setQueue(previous => reconcileQueue(previous, [...(snapshot.orders ?? [])].reverse(), workerId, bagging.current));
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
  }, [refresh, workerId]);

  useEffect(() => {
    let active = true;
    async function reserve() {
      const state = latestQueue.current.orders.find(item => item.order.order_id === selected);
      if (!state || isFulfilled(state) || heldByOther(state, workerId) || saving.current) return;
      if (ownedBy(state, workerId) && state.claim!.expires_at * 1000 - Date.now() > 60000) return;
      saving.current = true; epoch.current++; setBusy(true);
      try {
        const updated = await orderApi.claim(state.order.order_id, { worker_id: workerId, expected_revision: state.order.revision });
        if (active) setQueue(previous => ({ ...previous, orders: previous.orders.map(item => item.order.order_id === updated.order.order_id ? updated : item) }));
      } catch (cause) {
        if (active) setRefresh(value => value + 1);
        if (active && !(cause instanceof ApiError && cause.status === 409)) setActionError(cause instanceof Error ? cause.message : "Could not reserve this order.");
      } finally {
        saving.current = false;
        if (active) setBusy(false);
      }
    }
    void reserve();
    const timer = setInterval(() => void reserve(), 20000);
    return () => {
      active = false; clearInterval(timer);
      const state = latestQueue.current.orders.find(item => item.order.order_id === selected);
      if (state && !isFulfilled(state) && ownedBy(state, workerId)) void orderApi.claim(state.order.order_id, { worker_id: workerId, expected_revision: state.order.revision, release: true }).catch(() => { /* A disconnected screen's reservation expires. */ });
    };
  }, [selected, workerId, loading]);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (selected) url.searchParams.set("order", selected);
    else url.searchParams.delete("order");
    window.history.replaceState(null, "", url);
    list.current?.querySelector('[aria-pressed="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [selected, loading]);

  useEffect(() => {
    if (!undo) return;
    const timer = setTimeout(() => setUndo(null), Math.max(0, undo.expires - Date.now()));
    return () => clearTimeout(timer);
  }, [undo]);

  function offerUndo(id: string, revision: number) {
    setUndo({ id, revision, expires: Date.now() + 110000 });
  }

  async function submit(attempt: StatusAttempt) {
    if (saving.current) return;
    saving.current = true; epoch.current++;
    setPending(attempt); setBusy(true); setActionError(null); setNotice("");
    try {
      const state = latestQueue.current.orders.find(item => item.order.order_id === attempt.id);
      if (state && !ownedBy(state, workerId)) {
        const claimed = await orderApi.claim(attempt.id, { worker_id: workerId, expected_revision: attempt.body.expected_revision });
        attempt = { ...attempt, body: { ...attempt.body, expected_revision: claimed.order.revision } };
        setPending(attempt);
      }
      const updated = await orderApi.setStatus(attempt.id, attempt.body, attempt.key);
      setQueue(previous => {
        const next = reconcileQueue(previous, previous.orders.map(state => state.order.order_id === attempt.id ? updated : state), workerId);
        return attempt.restoreSelection ? { ...next, selected: attempt.id } : next;
      });
      if (attempt.body.status === "fulfilled") offerUndo(attempt.id, updated.order.revision);
      else setUndo(previous => previous?.id === attempt.id ? null : previous);
      setPending(null);
      setNotice(`#${orderNumber(attempt.id)} · ${toScreenState(updated).headline}`);
    } catch (error) {
      if (error instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(error.status)) {
        setPending(null);
        if (attempt.restoreSelection) setUndo(null);
      }
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
    if (status !== "fulfilled") setCameraPause(value => value + 1);
    void submit({ id: current.order.order_id, body: { worker_id: workerId, status, expected_revision: current.order.revision }, key: crypto.randomUUID() });
  }

  function undoFulfillment() {
    if (!undo || locked || Date.now() >= undo.expires) return;
    setCameraPause(value => value + 1);
    void submit({ id: undo.id, body: { worker_id: workerId, status: "unfulfilled", expected_revision: undo.revision }, key: crypto.randomUUID(), restoreSelection: true });
  }

  learnOrderNumbers(orders.map(state => state.order));
  // Oldest on the left, like tickets on a rail; the API sends newest first.
  // Fulfilled orders leave the rail; the one on screen stays until the mat is cleared.
  const rail = [...orders].reverse().filter(state => !isFulfilled(state) || state.order.order_id === selected);
  return (
    <div className="fulfillment-page">
      <div className="queue-toolbar">
        <nav ref={list} className="order-queue" aria-label="Orders, oldest first" tabIndex={0}>
          {!loading && !error && !orders.length && <p className="queue-empty">No orders yet</p>}
          {rail.map(state => {
            const screen = toScreenState(state);
            return <button className={`queue-ticket queue-${screen.tone}`} key={state.order.order_id} aria-pressed={state.order.order_id === selected} disabled={locked || heldByOther(state, workerId)} title={heldByOther(state, workerId) ? "On another screen" : amberReason(screen) ?? screen.headline} onClick={() => { setQueue(previous => ({ ...previous, selected: state.order.order_id })); setActionError(null); }}>
              <span className="queue-ticket-dot" aria-label={screen.headline} />
              <strong>#{orderNumber(state.order.order_id)}</strong>
              {heldByOther(state, workerId) && <span className="queue-ticket-owner">On another screen</span>}
            </button>;
          })}
        </nav>
        <span className="queue-status"><span className={`connection-dot ${error ? "offline" : loading ? "loading" : ""}`} />{error ? "Reconnecting…" : loading ? "Connecting…" : waiting ? `${waiting} to check` : "All caught up"}</span>
        <StartFreshButton />
      </div>
      {error && <div className="connection-error" role="alert">{error}</div>}
      {actionError && <div className="connection-error" role="alert">{actionError}{pending && <button className="secondary-button" disabled={busy} onClick={() => void submit(pending)}>{busy ? "Saving…" : "Retry status"}</button>}</div>}
      <div className="queue-announcement" role="status">{notice}</div>
      {undo && <div className="fulfillment-undo" role="status"><span>#{orderNumber(undo.id)} fulfilled</span><button className="secondary-button" disabled={locked} onClick={undoFulfillment}>Undo</button></div>}
      <div className={`fulfillment-layout tone-${currentTone ?? "waiting"}`}>
        <div className="active-ticket">
          {error ? <div className="empty-state" role="status"><h1>Reconnecting…</h1></div>
            : loading ? <div className="empty-state" role="status"><h1>Loading orders…</h1></div>
            : current ? <>
              <StationScreen state={current} />
              <div className="fulfillment-actions" aria-label="Manual override">
                <span>Override</span>
                {currentTone !== "green" && <button className="text-button" disabled={locked} onClick={() => setCheckNow(value => value + 1)}>Check now</button>}
                {currentTone !== "red" && <button className="text-button" disabled={locked} onClick={() => updateStatus("unfulfilled")}>Reopen</button>}
                {currentTone !== "amber" && <button className="text-button" disabled={locked} onClick={() => updateStatus("unsure")}>Needs review</button>}
                {currentTone !== "green" && <button className="text-button" disabled={locked} onClick={() => updateStatus("fulfilled")}>{busy ? "Saving…" : "Fulfill order"}</button>}
              </div>
            </>
            : <div className="empty-state"><h1>{waiting ? "No newer orders" : orders.length ? "All caught up" : "Waiting for orders"}</h1><p>{waiting ? "Pick an order above." : "New orders show up here on their own."}</p></div>}
        </div>
          <CameraCheckPanel workerId={workerId} order={current} disabled={locked || !current || !ownedBy(current, workerId)} pauseToken={cameraPause} checkToken={checkNow} onBusyChange={value => {
            saving.current = value; setBusy(value);
            if (value) epoch.current++;
            else setRefresh(count => count + 1);
          }} onResult={(updated, watching) => {
            if (isFulfilled(updated)) offerUndo(updated.order.order_id, updated.order.revision);
            bagging.current = watching ? updated.order.order_id : null;
            setQueue(previous => reconcileQueue(previous, previous.orders.map(state => state.order.order_id === updated.order.order_id ? updated : state), workerId, bagging.current));
            setNotice(`#${orderNumber(updated.order.order_id)} · ${toScreenState(updated).headline}`);
          }} onMatCleared={orderId => {
            if (bagging.current !== orderId) return;
            bagging.current = null;
            setQueue(previous => previous.selected === orderId ? advancePastHeld(previous, workerId) : previous);
          }} />
      </div>
    </div>
  );
}
