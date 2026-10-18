import type { MenuCategory, MenuEntry } from "../../api/client";

export interface MenuGroup { id: string; name: string | null; items: MenuEntry[] }

// Items under their category, in the menu's category order. Items without one go
// last under "Other"; a menu with no categories at all is one unnamed group.
export function groupMenu(items: MenuEntry[], categories: MenuCategory[] = []): MenuGroup[] {
  const known = new Set(categories.map(category => category.category_id));
  const groups: MenuGroup[] = categories.map(category => ({ id: category.category_id, name: category.name, items: items.filter(item => item.category_id === category.category_id) }));
  const other = items.filter(item => !item.category_id || !known.has(item.category_id));
  if (!categories.length) return [{ id: "all", name: null, items }];
  if (other.length) groups.push({ id: "other", name: "Other", items: other });
  return groups;
}
