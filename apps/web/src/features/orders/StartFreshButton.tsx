import { useState } from "react";
import { orderApi } from "../../api/client";
import { forgetLocalHistory } from "../../settings";

// Clears every open ticket and this browser's logs, so a demo can start again at #001.
export function StartFreshButton() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function startFresh() {
    if (!window.confirm("Clear every order in the queue and this browser's logs? New orders start again at #001.")) return;
    setBusy(true); setError("");
    try { await orderApi.clearStation(); } catch (cause) { setBusy(false); setError(cause instanceof Error ? cause.message : "Could not clear the queue."); return; }
    forgetLocalHistory();
    window.location.reload();
  }

  return <>
    {error && <span role="alert" className="settings-error">{error}</span>}
    <button className="secondary-button" disabled={busy} onClick={() => void startFresh()} title="Clear the queue and start again at #001">{busy ? "Clearing…" : "Start fresh"}</button>
  </>;
}
