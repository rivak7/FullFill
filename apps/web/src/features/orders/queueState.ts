import type { OrderState } from "../../api/generated/contracts";
import { toScreenState } from "../station/screenState";

export interface QueueState { orders: OrderState[]; selected: string | null }
export const isFulfilled = (state: OrderState) => toScreenState(state).tone === "green";

export const heldByOther = (state: OrderState, workerId?: string) => !!workerId && !!state.claim && state.claim.expires_at * 1000 > Date.now() && state.claim.worker_id !== workerId;
export const ownedBy = (state: OrderState, workerId: string) => !!state.claim && state.claim.worker_id === workerId && state.claim.expires_at * 1000 > Date.now();

export function reconcileQueue(previous: QueueState, incoming: OrderState[], workerId?: string): QueueState {
  // Both arrays are displayed newest first, with the oldest ticket at the bottom.
  // A slow read must not overwrite a newer acknowledged status change.
  const orders = incoming.map(state => {
    const saved = previous.orders.find(item => item.order.order_id === state.order.order_id);
    return saved && saved.order.revision > state.order.revision ? saved : state;
  });
  const beforeIndex = previous.orders.findIndex(state => state.order.order_id === previous.selected);
  const currentIndex = orders.findIndex(state => state.order.order_id === previous.selected);
  const before = previous.orders[beforeIndex];
  const current = orders[currentIndex];
  const justFulfilled = before && !isFulfilled(before) && current && isFulfilled(current);
  // New arrivals never steal focus, and intentionally selected history stays put.
  if (current && !justFulfilled && !heldByOther(current, workerId)) return { orders, selected: previous.selected };

  let candidates = orders;
  if (before) {
    if (current) {
      candidates = orders.slice(0, currentIndex);
    } else {
      // Cleanup can remove the completed ticket before another screen sees its
      // green state. Surviving older neighbors still mark where it used to sit.
      const olderIds = new Set(previous.orders.slice(beforeIndex + 1).map(state => state.order.order_id));
      const olderIndex = orders.findIndex(state => olderIds.has(state.order.order_id));
      candidates = olderIndex < 0 ? orders : orders.slice(0, olderIndex);
    }
  } else if (previous.orders.length && previous.selected === null) {
    // At the top, wait for new work; don't wrap back down on the next poll.
    const knownIds = new Set(previous.orders.map(state => state.order.order_id));
    candidates = orders.filter(state => !knownIds.has(state.order.order_id) || previous.orders.some(old => old.order.order_id === state.order.order_id && !!old.claim && old.claim.worker_id !== workerId && !heldByOther(state, workerId)));
  }

  // Work upward one unresolved ticket at a time, including orange tickets.
  // On the first load this starts at the oldest unresolved ticket at the bottom.
  return { orders, selected: [...candidates].reverse().find(state => !isFulfilled(state) && !heldByOther(state, workerId))?.order.order_id ?? null };
}
