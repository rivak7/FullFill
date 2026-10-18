// Restaurants call orders by a short number, not the POS id. Every screen derives the
// same 3-digit number (100-999) from the id, so the order site and kitchen agree.
export function orderNumber(orderId: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < orderId.length; i++) hash = Math.imul(hash ^ orderId.charCodeAt(i), 0x01000193);
  return String(100 + ((hash >>> 0) % 900));
}
