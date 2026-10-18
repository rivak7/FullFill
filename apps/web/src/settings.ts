// Kitchen settings, remembered per browser. Each one makes checks slower, so all are off
// by default; turn them on from Settings while debugging.
// - boxes: Perceptron also returns where each item is, drawn on photos in the CV logs.
// - photos: the API also returns the exact images sent to Perceptron (large responses).
// - reasoning: how hard Perceptron thinks before answering. "auto" lets the API choose
//   from the order size; the others force a mode for testing.
import { useSyncExternalStore } from "react";

export type Reasoning = "auto" | "none" | "low" | "high";
export interface KitchenSettings { boxes: boolean; photos: boolean; reasoning: Reasoning }

const storageKey = "fullfill.settings.v1";
const defaults: KitchenSettings = { boxes: false, photos: false, reasoning: "auto" };
const listeners = new Set<() => void>();
let cached: { raw: string | null; value: KitchenSettings } | null = null;
let memory: string | null = null; // When storage is blocked, settings last for this tab.

function stored(): string | null {
  try { return localStorage.getItem(storageKey); } catch { return memory; }
}

// The same object until a setting changes, as React's external stores expect.
export function readSettings(): KitchenSettings {
  const raw = stored();
  if (cached?.raw !== raw) {
    let value = { ...defaults };
    try { value = { ...defaults, ...JSON.parse(raw ?? "{}") }; } catch { /* Defaults. */ }
    cached = { raw, value };
  }
  return cached!.value;
}

export function changeSetting<K extends keyof KitchenSettings>(key: K, value: KitchenSettings[K]) {
  memory = JSON.stringify({ ...readSettings(), [key]: value });
  try { localStorage.setItem(storageKey, memory); } catch { /* Kept in memory. */ }
  listeners.forEach(listener => listener());
}

export function useSettings(): KitchenSettings {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => listeners.delete(listener); }, readSettings);
}

// Clears what this browser remembers between reloads: CV logs and the check counter.
export function forgetLocalHistory() {
  try {
    sessionStorage.removeItem("fullfill.cv-logs.v1");
    for (const key of Object.keys(localStorage)) if (key.startsWith("fullfill.check-attempt.")) localStorage.removeItem(key);
  } catch { /* Nothing stored. */ }
}
