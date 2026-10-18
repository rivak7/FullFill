import type { OrderState } from "../../api/generated/contracts";
import { toScreenState } from "../station/screenState";

export interface QueueState { orders: OrderState[]; selected: string | null }
export const isFulfilled = (state: OrderState) => toScreenState(state).tone === "green";

export function reconcileQueue(previous: QueueState, incoming: OrderState[]): QueueState {
  // A slow read must not overwrite a newer acknowledged status change.
  const orders = incoming.map(state => {
    const saved = previous.orders.find(item => item.order.order_id === state.order.order_id);
    return saved && saved.order.revision > state.order.revision ? saved : state;
  });
  const before = previous.orders.find(state => state.order.order_id === previous.selected);
  const current = orders.find(state => state.order.order_id === previous.selected);
  const justFulfilled = before && !isFulfilled(before) && current && isFulfilled(current);
  // Keep intentional selections, including completed history. New work never
  // steals focus. Completion/removal advances to the oldest unresolved ticket.
  const selected = current && !justFulfilled ? previous.selected
    : orders.find(state => !isFulfilled(state))?.order.order_id ?? null;
  return { orders, selected };
}
