// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { orderApi, type MenuEntry } from "../src/api/client";
import { MenuEditor } from "../src/features/orders/MenuEditor";
import { groupMenu } from "../src/features/orders/menuGroups";

vi.mock("../src/api/client", async importOriginal => ({
  ...await importOriginal<typeof import("../src/api/client")>(),
  orderApi: { managedMenu: vi.fn(), addMenuCategory: vi.fn(), saveMenu: vi.fn() },
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

const entry = (item_id: string, name: string, category_id: string | null = null): MenuEntry => ({ item_id, name, description: "", price_cents: 400, currency: "USD", available: true, archived: false, version: 1, photo_id: null, photo_url: "https://images.example.com/x.png", category_id });

it("groups items by category with uncategorized ones last, and leaves a menu without categories flat", () => {
  const sauces = { category_id: "c2", name: "Sauces" }, sides = { category_id: "c1", name: "Sides" };
  const groups = groupMenu([entry("fries", "Fries", "c1"), entry("ketchup", "Ketchup", "c2"), entry("bowl", "Bowl"), entry("lost", "Lost", "gone")], [sauces, sides]);
  expect(groups.map(group => [group.name, group.items.map(item => item.item_id)])).toEqual([["Sauces", ["ketchup"]], ["Sides", ["fries"]], ["Other", ["bowl", "lost"]]]);
  expect(groupMenu([entry("fries", "Fries")])).toEqual([{ id: "all", name: null, items: [entry("fries", "Fries")] }]);
});

it("adds a category and files an item under it", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fries = entry("fries", "Fries");
  vi.mocked(orderApi.managedMenu).mockResolvedValue({ revision: "1", items: [fries], categories: [] });
  const withSides = { revision: "2", items: [fries], categories: [{ category_id: "c1", name: "Sides" }] };
  vi.mocked(orderApi.addMenuCategory).mockResolvedValue(withSides);
  vi.mocked(orderApi.saveMenu).mockResolvedValue({ ...withSides, items: [{ ...fries, category_id: "c1", version: 2 }] });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const button = (text: string) => [...container.querySelectorAll("button")].find(button => button.textContent === text)!;
  const type = async (element: HTMLInputElement | HTMLSelectElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value")!.set!;
    await act(async () => { setter.call(element, value); element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); });
  };
  try {
    await act(async () => root.render(<MenuEditor />));
    await act(async () => button("+ Add category").click());
    await type(container.querySelector<HTMLInputElement>("#category-name")!, " Sides ");
    await act(async () => button("Add").click());
    expect(orderApi.addMenuCategory).toHaveBeenCalledWith("Sides", expect.any(String));
    expect(container.querySelector(".menu-group-name")?.textContent).toBe("Sides0");
    expect(container.textContent).toContain("Other");
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Edit Fries"]')!.click());
    await type(container.querySelector<HTMLSelectElement>("#item-category")!, "c1");
    await act(async () => button("Save item").click());
    expect(orderApi.saveMenu).toHaveBeenCalledWith(expect.objectContaining({ item_id: "fries", category_id: "c1" }), expect.any(String));
    expect(container.querySelector(".menu-group-name")?.textContent).toBe("Sides1");
    expect(container.textContent).not.toContain("Other");
  } finally { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); }
});
