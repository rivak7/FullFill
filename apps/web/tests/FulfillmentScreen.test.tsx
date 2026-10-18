// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { orderNumber } from "../src/orderNumber";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, orderApi } from "../src/api/client";
import type { OrderState, StationSnapshot } from "../src/api/generated/contracts";
import { FulfillmentScreen } from "../src/features/orders/FulfillmentScreen";
import { reconcileQueue } from "../src/features/orders/queueState";

vi.mock("../src/api/client", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/client")>(),
  orderApi: { claim: vi.fn(), station: vi.fn(), setStatus: vi.fn(), cameraConfig: vi.fn(), checkCamera: vi.fn() },
}));

function ticket(id: string, disposition: OrderState["disposition"] = "pending", revision = 1): OrderState {
  return { order: { schema_version: 1, order_id: id, revision, lines: [{ line_id: "line", item_id: "fries", name: "Fries", quantity: 1, verification_mode: "visible_item" }] }, disposition, disposition_revision: revision, current_check: null };
}
const snapshot = (orders: OrderState[]): StationSnapshot => ({ station_id: "main", orders });
let orders: OrderState[];
let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.useFakeTimers(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  window.history.replaceState(null, "", "/fulfill");
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  orders = [ticket("first"), ticket("second", "needs_review"), ticket("third")];
  vi.mocked(orderApi.claim).mockImplementation(async (id, edit) => {
    const state = orders.find(state => state.order.order_id === id)!;
    const updated = { ...state, claim: edit.release ? null : { worker_id: edit.worker_id, expires_at: Date.now() / 1000 + 120 } };
    orders = orders.map(state => state.order.order_id === id ? updated : state);
    return updated;
  });
  vi.mocked(orderApi.cameraConfig).mockResolvedValue({ configured: true });
  vi.mocked(orderApi.station).mockImplementation(async () => snapshot(orders));
  vi.mocked(orderApi.setStatus).mockImplementation(async (id, edit) => {
    const updated = ticket(id, edit.status === "fulfilled" ? "overridden" : edit.status === "unsure" ? "needs_review" : "pending", edit.expected_revision + 1);
    updated.claim = { worker_id: edit.worker_id, expires_at: Date.now() / 1000 + 120 };
    orders = orders.map(state => state.order.order_id === id ? updated : state);
    return updated;
  });
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.resetAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals();
});
async function render() { await act(async () => root.render(<FulfillmentScreen />)); }
async function click(text: string) {
  const button = [...container.querySelectorAll("button")].find(button => button.textContent === text);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
const selected = () => container.querySelector('.queue-ticket[aria-pressed="true"]')?.textContent;
async function poll() { await act(async () => vi.advanceTimersByTimeAsync(1000)); }

it("shows another screen's changes on the next one-second refresh", async () => {
  await render();
  orders[0] = ticket("first", "overridden", 2);
  await act(async () => vi.advanceTimersByTimeAsync(999));
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(orderApi.station).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(selected()).toContain(`#${orderNumber("second")}`);
  expect(container.querySelector(".queue-green")?.textContent).toContain(`#${orderNumber("first")}`);
});

it("waits for a slow refresh before starting another request", async () => {
  let resolve!: (snapshot: StationSnapshot) => void;
  vi.mocked(orderApi.station).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await render();
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(orderApi.station).toHaveBeenCalledTimes(1);
  await act(async () => resolve(snapshot(orders)));
  await poll();
  expect(orderApi.station).toHaveBeenCalledTimes(2);
});

it("backs off repeated failures up to thirty seconds and resumes fast refresh after recovery", async () => {
  vi.mocked(orderApi.station).mockRejectedValue(new Error("Square is busy."));
  await render();
  let calls = 1;
  for (const delay of [3000, 6000, 12000, 24000, 30000, 30000]) {
    await act(async () => vi.advanceTimersByTimeAsync(delay - 1));
    expect(orderApi.station).toHaveBeenCalledTimes(calls);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(orderApi.station).toHaveBeenCalledTimes(++calls);
  }
  vi.mocked(orderApi.station).mockImplementation(async () => snapshot(orders));
  await act(async () => vi.advanceTimersByTimeAsync(30000));
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(orderApi.station).toHaveBeenCalledTimes(++calls);
  await poll();
  expect(orderApi.station).toHaveBeenCalledTimes(++calls);
});

it("colors the queue, advances to orange work, and keeps completed tickets selectable", async () => {
  await render();
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect([...container.querySelectorAll(".queue-ticket strong")].map(card => card.textContent)).toEqual([`#${orderNumber("first")}`, `#${orderNumber("second")}`, `#${orderNumber("third")}`]);
  expect(container.querySelector(".order-queue")?.getAttribute("aria-label")).toBe("Orders, oldest first");
  expect(container.querySelector(".queue-amber")?.textContent).toContain(`#${orderNumber("second")}`);
  await click("Fulfill order");
  expect(selected()).toContain(`#${orderNumber("second")}`);
  expect(window.location.search).toBe("?order=second");
  expect(container.querySelector(".queue-green")?.textContent).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".station.tone-amber")).not.toBeNull();
  await act(async () => (container.querySelector(".queue-green") as HTMLButtonElement).click());
  await poll();
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".station.tone-green")).not.toBeNull();
  await click("Reopen");
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".station.tone-red")).not.toBeNull();
});

it("keeps the current ticket on arrivals or orange status and advances on another screen's fulfillment", async () => {
  await render(); await click("Needs review");
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".station.tone-amber")).not.toBeNull();
  orders.push(ticket("newest")); await poll();
  expect(selected()).toContain(`#${orderNumber("first")}`);
  orders[0] = ticket("first", "overridden", 3); await poll();
  expect(selected()).toContain(`#${orderNumber("second")}`);
});

it("keeps unresolved overflow visible and shows caught up only after the last unresolved ticket", async () => {
  orders = Array.from({ length: 12 }, (_, i) => ticket(`order-${i}`));
  await render(); expect(container.querySelectorAll(".queue-ticket")).toHaveLength(12);
  orders = [ticket("order-0", "overridden", 2)]; await poll();
  expect(container.querySelector("h1")?.textContent).toBe("All caught up");
  expect(window.location.search).toBe("");
  orders.push(ticket("new")); await poll();
  expect(selected()).toContain(`#${orderNumber("new")}`);
});

it("does not advance on a failed write and retries the exact same attempt", async () => {
  vi.mocked(orderApi.setStatus).mockRejectedValueOnce(new Error("Offline"));
  await render(); await click("Fulfill order");
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".queue-green")).toBeNull();
  const attempt = vi.mocked(orderApi.setStatus).mock.calls[0];
  await click("Retry status");
  expect(vi.mocked(orderApi.setStatus).mock.calls[1]).toEqual(attempt);
  expect(selected()).toContain(`#${orderNumber("second")}`);
});

it("refreshes a conflict without silently overwriting the other screen", async () => {
  vi.mocked(orderApi.setStatus).mockImplementationOnce(async () => {
    orders[0] = ticket("first", "needs_review", 2);
    throw new ApiError("This order changed on another screen.", 409);
  });
  await render(); await click("Fulfill order");
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".station.tone-amber")).not.toBeNull();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("another screen");
  expect(orderApi.setStatus).toHaveBeenCalledTimes(1);
});

it("ignores an in-flight poll from before a status save", async () => {
  await render();
  let resolve!: (snapshot: StationSnapshot) => void;
  vi.mocked(orderApi.station).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await poll();
  await click("Fulfill order");
  await act(async () => resolve(snapshot([ticket("first"), ticket("second", "needs_review"), ticket("third")])));
  expect(selected()).toContain(`#${orderNumber("second")}`);
  expect(container.querySelector(".queue-green")?.textContent).toContain(`#${orderNumber("first")}`);
});

it("advances if cleanup removes the current ticket, keeps newer revisions, and skips green on initial load", () => {
  const first = ticket("first", "overridden", 2);
  const second = ticket("second", "needs_review");
  expect(reconcileQueue({ orders: [], selected: null }, [second, first]).selected).toBe("second");
  expect(reconcileQueue({ orders: [second, first], selected: "first" }, [second]).selected).toBe("second");
  expect(reconcileQueue({ orders: [second, first], selected: "second" }, [second, ticket("first")]).orders[1]).toEqual(first);
});

it("fulfills the fourth card and moves up to the third, then second, then first", async () => {
  orders = Array.from({ length: 6 }, (_, i) => ticket(`order-${i + 1}`));
  window.history.replaceState(null, "", "/fulfill?order=order-3");
  await render();
  expect([...container.querySelectorAll(".queue-ticket strong")].map(card => card.textContent)).toEqual([`#${orderNumber("order-1")}`, `#${orderNumber("order-2")}`, `#${orderNumber("order-3")}`, `#${orderNumber("order-4")}`, `#${orderNumber("order-5")}`, `#${orderNumber("order-6")}`]);
  expect(selected()).toContain(`#${orderNumber("order-3")}`);
  for (const next of [`#${orderNumber("order-4")}`, `#${orderNumber("order-5")}`, `#${orderNumber("order-6")}`]) {
    await click("Fulfill order");
    expect(selected()).toContain(next);
    await poll();
    expect(selected()).toContain(next);
  }
});

it("moves upward past green cards to the next orange card", async () => {
  orders = [ticket("oldest"), ticket("current"), ticket("done", "overridden"), ticket("review", "needs_review"), ticket("newest")];
  window.history.replaceState(null, "", "/fulfill?order=current");
  await render(); await click("Fulfill order");
  expect(selected()).toContain(`#${orderNumber("review")}`);
  expect(container.querySelector('.queue-ticket[aria-pressed="true"]')?.classList.contains("queue-amber")).toBe(true);
  expect([...container.querySelectorAll(".queue-green")].map(card => card.textContent)).toEqual([expect.stringContaining(`#${orderNumber("current")}`), expect.stringContaining(`#${orderNumber("done")}`)]);
});

it("preserves the upward position when another screen completes and cleanup removes the current card", async () => {
  orders = Array.from({ length: 6 }, (_, i) => ticket(`order-${i + 1}`));
  window.history.replaceState(null, "", "/fulfill?order=order-3");
  await render();
  orders = orders.filter(state => state.order.order_id !== "order-3");
  orders.push(ticket("order-7"));
  await poll();
  expect(selected()).toContain(`#${orderNumber("order-4")}`);
});

it("waits at the top instead of wrapping to older work, then resumes when new orders arrive", async () => {
  orders = [ticket("older"), ticket("current")];
  window.history.replaceState(null, "", "/fulfill?order=current");
  await render(); await click("Fulfill order");
  expect(selected()).toBeUndefined();
  expect(container.querySelector("h1")?.textContent).toBe("No newer orders");
  await poll();
  expect(selected()).toBeUndefined();
  orders.push(ticket("new-a"), ticket("new-b"));
  await poll();
  expect(selected()).toContain(`#${orderNumber("new-a")}`);
  await click("Fulfill order");
  expect(selected()).toContain(`#${orderNumber("new-b")}`);
});

it("undoes a mistaken fulfillment and returns to that ticket without an AI call", async () => {
  await render(); await click("Fulfill order");
  expect(selected()).toContain(`#${orderNumber("second")}`);
  await click("Undo");
  expect(selected()).toContain(`#${orderNumber("first")}`);
  expect(container.querySelector(".station.tone-red")).not.toBeNull();
  expect(container.querySelector(".fulfillment-undo")).toBeNull();
  expect(orderApi.setStatus).toHaveBeenLastCalledWith("first", { worker_id: expect.any(String), status: "unfulfilled", expected_revision: 2 }, expect.any(String));
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  await poll();
  expect(selected()).toContain(`#${orderNumber("first")}`);
});

it("a stale Undo cannot overwrite another worker's newer decision", async () => {
  await render(); await click("Fulfill order");
  orders[0] = ticket("first", "needs_review", 3);
  vi.mocked(orderApi.setStatus).mockRejectedValueOnce(new ApiError("Order changed. Refresh before correcting it.", 409));
  await click("Undo");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Order changed");
  expect(orderApi.setStatus).toHaveBeenLastCalledWith("first", { worker_id: expect.any(String), status: "unfulfilled", expected_revision: 2 }, expect.any(String));
  expect([...container.querySelectorAll(".queue-amber")].map(card => card.textContent)).toContain(`#${orderNumber("second")}`);
});

it("skips another screen's reservation and marks that ticket in the queue", async () => {
  orders[0].claim = { worker_id: "someone-else", expires_at: Date.now() / 1000 + 120 };
  await render();
  expect(selected()).toContain(`#${orderNumber("second")}`);
  const held = [...container.querySelectorAll<HTMLButtonElement>(".queue-ticket")].find(card => card.textContent?.includes(`#${orderNumber("first")}`))!;
  expect(held.disabled).toBe(true);
  expect(held.textContent).toContain("On another screen");
  expect(orderApi.claim).toHaveBeenCalledWith("second", expect.objectContaining({ worker_id: expect.any(String) }));
});

it("renews its reservation and releases it when switching tickets", async () => {
  await render();
  const initial = vi.mocked(orderApi.claim).mock.calls[0];
  await act(async () => vi.advanceTimersByTimeAsync(61000));
  expect(orderApi.claim).toHaveBeenCalledTimes(2);
  expect(vi.mocked(orderApi.claim).mock.calls[1][1].worker_id).toBe(initial[1].worker_id);
  await act(async () => [...container.querySelectorAll<HTMLButtonElement>(".queue-ticket")].at(-1)!.click());
  expect(orderApi.claim).toHaveBeenCalledWith("first", expect.objectContaining({ release: true, worker_id: initial[1].worker_id }));
});

it("two screens race for one ticket and the loser moves to the next available order", async () => {
  vi.mocked(orderApi.claim).mockImplementationOnce(async () => {
    orders[0] = { ...orders[0], claim: { worker_id: "another-screen", expires_at: Date.now() / 1000 + 120 }, order: { ...orders[0].order, revision: 2 } };
    throw new ApiError("Another screen is working on this order.", 409);
  });
  await render();
  expect(selected()).toContain(`#${orderNumber("second")}`);
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

it("picks up a released reservation when every ticket was previously occupied", () => {
  const held = ticket("held"); held.claim = { worker_id: "other", expires_at: Date.now() / 1000 - 1 };
  expect(reconcileQueue({ selected: null, orders: [held] }, [ticket("held", "pending", 2)], "ours").selected).toBe("held");
});
