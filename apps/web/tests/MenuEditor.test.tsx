// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { orderApi, type MenuEntry } from "../src/api/client";
import { MenuEditor } from "../src/features/orders/MenuEditor";

vi.mock("../src/api/client", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/client")>(),
  orderApi: { managedMenu: vi.fn() },
}));

it("shows active items without a deleted-items or restore option", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const item: MenuEntry = { item_id: "fries", name: "Fries", description: "", price_cents: 400, currency: "USD", available: true, archived: false, version: 1, photo_id: null, photo_url: null };
  vi.mocked(orderApi.managedMenu).mockResolvedValue({ revision: "1", items: [item, { ...item, item_id: "removed", name: "Old item", archived: true }] });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<MenuEditor />));
    expect(container.textContent).toContain("Fries");
    expect(container.textContent).not.toMatch(/Old item|Deleted|Restore/);
    expect(container.querySelector('[aria-label="Item filter"]')).toBeNull();
  } finally { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); }
});
