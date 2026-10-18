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
it("checks kitchen scope and keeps kitchen content hidden from ordering credentials", async () => {
  vi.mocked(orderApi.session).mockResolvedValue({ required: true, authenticated: false, role: "order" });
  await act(async () => root.render(<AccessGate scope="kitchen"><p>Private kitchen</p></AccessGate>));
  expect(orderApi.session).toHaveBeenCalledWith("kitchen", expect.any(AbortSignal));
  expect(container.textContent).toContain("Kitchen access");
  expect(container.textContent).not.toContain("Private kitchen");
});
it("renders ordering for its credential and rechecks if the screen scope changes", async () => {
  vi.mocked(orderApi.session).mockResolvedValue({ required: true, authenticated: true, role: "order" });
  await act(async () => root.render(<AccessGate scope="order"><p>Order menu</p></AccessGate>));
  expect(container.textContent).toBe("Order menu");
  vi.mocked(orderApi.session).mockResolvedValue({ required: true, authenticated: false, role: "order" });
  await act(async () => root.render(<AccessGate scope="kitchen"><p>Private kitchen</p></AccessGate>));
  expect(container.textContent).not.toContain("Private kitchen");
  expect(container.textContent).toContain("Kitchen access");
});
