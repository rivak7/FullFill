// Dev mode is for debugging the kitchen: open any page with ?dev=1 (or ?dev=0 to leave).
// It returns photos, boxes and server timings with each check, and offers "Start fresh".
// Normal mode keeps checks lean: no images or boxes come back with the answer.
const storageKey = "fullfill.dev.v1";

export function isDevMode(): boolean {
  try {
    const flag = new URLSearchParams(window.location.search).get("dev");
    if (flag === "1") localStorage.setItem(storageKey, "1");
    if (flag === "0") localStorage.removeItem(storageKey);
    return localStorage.getItem(storageKey) === "1";
  } catch {
    return false;
  }
}

// Clears what this browser remembers between reloads: CV logs and the check counter.
export function forgetLocalHistory() {
  try {
    sessionStorage.removeItem("fullfill.cv-logs.v1");
    for (const key of Object.keys(localStorage)) if (key.startsWith("fullfill.check-attempt.")) localStorage.removeItem(key);
  } catch { /* Nothing stored. */ }
}
