import type { OrderSnapshot } from "./api/generated/contracts";

// Restaurants call orders by a short number. The API numbers FullFill orders 001, 002...
// and the screens remember each number so logs and banners that only hold an id agree.
const known = new Map<string, string>();

export function learnOrderNumbers(orders: Pick<OrderSnapshot, "order_id" | "display_number">[]) {
  for (const order of orders) if (order.display_number) known.set(order.order_id, order.display_number);
}

export function orderNumber(orderId: string): string {
  const number = known.get(orderId);
  if (number) return number;
  // Orders placed outside FullFill (e.g. straight into Square) have no number: use a stable 3 digits.
  let hash = 0x811c9dc5;
  for (let i = 0; i < orderId.length; i++) hash = Math.imul(hash ^ orderId.charCodeAt(i), 0x01000193);
  return String(100 + ((hash >>> 0) % 900));
}
