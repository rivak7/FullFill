import { useEffect, useState } from "react";

const prefix = "fullfill.check-attempt.v1.";
const changed = "fullfill:check-activity";
const day = 24 * 60 * 60 * 1000;
let storageFailed = false;

// One key per attempt avoids lost increments when two tabs check simultaneously.
// Only timestamps are retained, for at most 24 hours; no images or ticket details.
export function readCheckActivity(now = Date.now()): number[] | null {
  try {
    const timestamps: number[] = [];
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith(prefix)) continue;
      const time = Number(localStorage.getItem(key));
      if (Number.isFinite(time) && time > now - day && time <= now) timestamps.push(time);
      else localStorage.removeItem(key);
    }
    return storageFailed ? null : timestamps;
  } catch { return null; }
}

export function recordCheckAttempt(id: string) {
  readCheckActivity();
  try { localStorage.setItem(prefix + id, String(Date.now())); }
  catch { storageFailed = true; }
  window.dispatchEvent(new Event(changed));
}

export function CheckActivity() {
  const [open, setOpen] = useState(false);
  const [minutes, setMinutes] = useState(60);
  const [activity, setActivity] = useState<{ times: number[] | null; now: number }>({ times: [], now: Date.now() });
  useEffect(() => {
    if (!open) return;
    const update = () => { const now = Date.now(); setActivity({ times: readCheckActivity(now), now }); };
    update();
    const timer = window.setInterval(update, 5000);
    window.addEventListener(changed, update);
    window.addEventListener("storage", update);
    return () => { window.clearInterval(timer); window.removeEventListener(changed, update); window.removeEventListener("storage", update); };
  }, [open]);
  const count = activity.times?.filter(time => time > activity.now - minutes * 60000).length;
  return <details className="check-activity" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Check activity</summary>
    <div className="check-activity-row">
      <label>Last <select aria-label="Check activity period" value={minutes} onChange={event => setMinutes(Number(event.target.value))}>
        <option value={5}>5 minutes</option><option value={60}>hour</option><option value={1440}>24 hours</option>
      </select></label>
      <output aria-live="polite">{count === undefined ? "History unavailable" : `${count} check attempt${count === 1 ? "" : "s"}`}</output>
    </div>
    <small>This browser · Includes failed attempts · Not a billing total</small>
  </details>;
}
