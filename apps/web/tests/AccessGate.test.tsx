// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { orderApi } from "../src/api/client";
import { AccessGate } from "../src/features/access/AccessGate";

vi.mock("../src/api/client", () => ({ orderApi: { session: vi.fn() }, setAccessKey: vi.fn() }));
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.resetAllMocks(); vi.unstubAllGlobals();
});
it.each(["order", "kitchen"] as const)("uses the same access prompt on the %s screen", async scope => {
  vi.mocked(orderApi.session).mockResolvedValue({ required: true, authenticated: false, role: null });
  await act(async () => root.render(<AccessGate scope={scope}><p>Screen content</p></AccessGate>));
  expect(container.textContent).toContain("FullFill access");
  expect(container.textContent).not.toContain("Screen content");
  expect(container.textContent).not.toContain("Kitchen access");
});
it("accepts the shared authenticated session on both screens", async () => {
  vi.mocked(orderApi.session).mockResolvedValue({ required: true, authenticated: true, role: "kitchen" });
  await act(async () => root.render(<AccessGate scope="order"><p>Order menu</p></AccessGate>));
  expect(container.textContent).toBe("Order menu");
  await act(async () => root.render(<AccessGate scope="kitchen"><p>Kitchen queue</p></AccessGate>));
  expect(container.textContent).toBe("Kitchen queue");
});
