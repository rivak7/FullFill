// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, orderApi } from "../src/api/client";
import type { OrderState, StationSnapshot } from "../src/api/generated/contracts";
import { FulfillmentScreen } from "../src/features/orders/FulfillmentScreen";
import { reconcileQueue } from "../src/features/orders/queueState";

vi.mock("../src/api/client", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/client")>(),
  orderApi: { station: vi.fn(), setStatus: vi.fn() },
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
  vi.mocked(orderApi.station).mockImplementation(async () => snapshot(orders));
  vi.mocked(orderApi.setStatus).mockImplementation(async (id, edit) => {
    const updated = ticket(id, edit.status === "fulfilled" ? "overridden" : edit.status === "unsure" ? "needs_review" : "pending", edit.expected_revision + 1);
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
  expect(selected()).toContain("#FIRST");
  expect(orderApi.station).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(selected()).toContain("#SECOND");
  expect(container.querySelector(".queue-green")?.textContent).toContain("#FIRST");
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
  expect(selected()).toContain("#FIRST");
  expect([...container.querySelectorAll(".queue-ticket strong")].map(card => card.textContent)).toEqual(["#THIRD", "#SECOND", "#FIRST"]);
  expect(container.querySelector(".queue-heading")?.textContent).toContain("Newest first");
  expect(container.querySelector(".queue-amber")?.textContent).toContain("#SECOND");
  await click("Fulfill order");
  expect(selected()).toContain("#SECOND");
  expect(window.location.search).toBe("?order=second");
  expect(container.querySelector(".queue-green")?.textContent).toContain("#FIRST");
  expect(container.querySelector(".station.tone-amber")).not.toBeNull();
  await act(async () => (container.querySelector(".queue-green") as HTMLButtonElement).click());
  await poll();
  expect(selected()).toContain("#FIRST");
  expect(container.querySelector(".station.tone-green")).not.toBeNull();
  await click("Reopen");
  expect(selected()).toContain("#FIRST");
  expect(container.querySelector(".station.tone-red")).not.toBeNull();
});

it("keeps the current ticket on arrivals or orange status and advances on another screen's fulfillment", async () => {
  await render(); await click("Needs review");
  expect(selected()).toContain("#FIRST");
  expect(container.querySelector(".station.tone-amber")).not.toBeNull();
  orders.push(ticket("newest")); await poll();
  expect(selected()).toContain("#FIRST");
  orders[0] = ticket("first", "overridden", 3); await poll();
  expect(selected()).toContain("#SECOND");
});

it("keeps unresolved overflow visible and shows caught up only after the last unresolved ticket", async () => {
  orders = Array.from({ length: 12 }, (_, i) => ticket(`order-${i}`));
  await render(); expect(container.querySelectorAll(".queue-ticket")).toHaveLength(12);
  orders = [ticket("order-0", "overridden", 2)]; await poll();
  expect(container.querySelector("h1")?.textContent).toBe("All caught up");
  expect(window.location.search).toBe("");
  orders.push(ticket("new")); await poll();
  expect(selected()).toContain("#NEW");
});

it("does not advance on a failed write and retries the exact same attempt", async () => {
  vi.mocked(orderApi.setStatus).mockRejectedValueOnce(new Error("Offline"));
  await render(); await click("Fulfill order");
  expect(selected()).toContain("#FIRST");
  expect(container.querySelector(".queue-green")).toBeNull();
  const attempt = vi.mocked(orderApi.setStatus).mock.calls[0];
  await click("Retry status");
  expect(vi.mocked(orderApi.setStatus).mock.calls[1]).toEqual(attempt);
  expect(selected()).toContain("#SECOND");
});

it("refreshes a conflict without silently overwriting the other screen", async () => {
  vi.mocked(orderApi.setStatus).mockImplementationOnce(async () => {
    orders[0] = ticket("first", "needs_review", 2);
    throw new ApiError("This order changed on another screen.", 409);
  });
  await render(); await click("Fulfill order");
  expect(selected()).toContain("#FIRST");
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
  expect(selected()).toContain("#SECOND");
  expect(container.querySelector(".queue-green")?.textContent).toContain("#FIRST");
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
  expect([...container.querySelectorAll(".queue-ticket strong")].map(card => card.textContent)).toEqual(["#ORDER-6", "#ORDER-5", "#ORDER-4", "#ORDER-3", "#ORDER-2", "#ORDER-1"]);
  expect(selected()).toContain("#ORDER-3");
  for (const next of ["#ORDER-4", "#ORDER-5", "#ORDER-6"]) {
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
  expect(selected()).toContain("#REVIEW");
  expect(container.querySelector('.queue-ticket[aria-pressed="true"]')?.classList.contains("queue-amber")).toBe(true);
  expect([...container.querySelectorAll(".queue-green")].map(card => card.textContent)).toEqual([expect.stringContaining("#DONE"), expect.stringContaining("#CURRENT")]);
});

it("preserves the upward position when another screen completes and cleanup removes the current card", async () => {
  orders = Array.from({ length: 6 }, (_, i) => ticket(`order-${i + 1}`));
  window.history.replaceState(null, "", "/fulfill?order=order-3");
  await render();
  orders = orders.filter(state => state.order.order_id !== "order-3");
  orders.push(ticket("order-7"));
  await poll();
  expect(selected()).toContain("#ORDER-4");
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
  expect(selected()).toContain("#NEW-A");
  await click("Fulfill order");
  expect(selected()).toContain("#NEW-B");
});
