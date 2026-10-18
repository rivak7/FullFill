import { useEffect, useState } from "react";
import type { CameraDiagnostics } from "../../api/client";
import type { OrderState } from "../../api/generated/contracts";

export type CheckTrigger = "manual" | "scene change" | "periodic" | "next order";
interface LogEvent { at: number; message: string }
export interface CvLog {
  id: string;
  orderId: string;
  revision: number;
  trigger: CheckTrigger;
  startedAt: number;
  finishedAt?: number;
  result: string;
  events: LogEvent[];
  diagnostics?: CameraDiagnostics;
}
const key = "fullfill.cv-logs.v1";
const changed = "fullfill:cv-logs";
let memory: CvLog[] = [];
const photos = new Map<string, { capture?: string; diagnostics?: CameraDiagnostics }>();

export function attachCvVisuals(id: string, value: { capture?: string; diagnostics?: CameraDiagnostics }) {
  photos.set(id, { ...photos.get(id), ...value });
  while (photos.size > 10) photos.delete(photos.keys().next().value!);
  const diagnostics = value.diagnostics;
  save(readCvLogs().map(log => log.id !== id || !diagnostics ? log : {
    ...log, diagnostics: { ...diagnostics, image: null, references: diagnostics.references.map(ref => ({ ...ref, image: null })) },
  }));
}


export function readCvLogs(): CvLog[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(key) ?? "[]");
    if (!Array.isArray(saved)) return [];
    memory = saved.filter((entry): entry is CvLog => !!entry && typeof entry.id === "string"
      && typeof entry.orderId === "string" && Number.isFinite(entry.startedAt)
      && typeof entry.result === "string" && Array.isArray(entry.events)
      && entry.events.every((event: LogEvent) => event && Number.isFinite(event.at) && typeof event.message === "string")).slice(0, 50);
  } catch { /* In-memory diagnostics still work if session storage is unavailable. */ }
  return memory;
}

function save(logs: CvLog[]) {
  memory = logs.slice(0, 50);
  try { sessionStorage.setItem(key, JSON.stringify(memory)); } catch { /* No effect on checks. */ }
  window.dispatchEvent(new Event(changed));
}

export function startCvLog(id: string, orderId: string, revision: number, trigger: CheckTrigger) {
  const now = Date.now();
  save([{ id, orderId, revision, trigger, startedAt: now, result: "Capturing", events: [] }, ...readCvLogs()]);
}

export function updateCvLog(id: string, message: string, result?: string, finished = false) {
  const now = Date.now();
  save(readCvLogs().map(log => log.id !== id ? log : {
    ...log, result: result ?? log.result,
    ...(finished ? { finishedAt: now } : {}),
    events: [...log.events, { at: now, message: message.slice(0, 2000) }].slice(-30),
  }));
}

export function checkResultDetails(state: OrderState): string {
  const check = state.current_check;
  return [check?.execution_status ?? "No check", check?.verdict, check?.error_code,
    ...(check?.discrepancies?.map(item => item.message) ?? [])].filter(Boolean).join(" · ");
}

export function sceneDiagnostic(reason: string | null | undefined): string {
  const labels: Record<string, string> = {
    scene_changed: "The image changed after capture",
    sampling_gap: "No camera sample for over one second",
    tab_hidden: "Kitchen tab was hidden",
    camera_stopped: "Camera was closed or switched",
    camera_disconnected: "Camera disconnected",
    camera_unavailable: "Camera stream was unavailable",
    ticket_changed: "Selected ticket or its items changed",
    page_closed: "Camera panel was closed",
    capture_error: "Could not read a camera frame",
  };
  return `${reason ?? "unknown"}${reason && labels[reason] ? ` (${labels[reason]})` : ""}`;
}

export function CvLogs({ order }: { order?: OrderState }) {
  const [logs, setLogs] = useState(readCvLogs);
  const [copyStatus, setCopyStatus] = useState("");
  useEffect(() => {
    const update = () => setLogs([...readCvLogs()]);
    window.addEventListener(changed, update);
    return () => window.removeEventListener(changed, update);
  }, []);
  const saved = order?.current_check ? {
    orderId: order.order.order_id, checkId: order.current_check.check_id,
    details: checkResultDetails(order),
  } : null;
  async function copy() {
    try { await navigator.clipboard.writeText(JSON.stringify({ latestSavedCheck: saved, checks: logs }, null, 2)); setCopyStatus("Copied"); }
    catch { setCopyStatus("Could not copy. You can select the log text below."); }
  }
  return <section className="cv-logs" aria-label="CV logs">
    <div className="cv-log-actions"><button type="button" className="secondary-button" onClick={() => void copy()}>Copy logs</button><button type="button" className="secondary-button" disabled={!logs.length} onClick={() => { photos.clear(); save([]); setCopyStatus(""); }}>Clear logs</button><span role="status">{copyStatus}</span></div>
    <small>Latest 50 checks · Photos for the last 10 checks until reload · Copy excludes photos</small>
    {saved && <p>Latest saved check · #{saved.orderId.slice(-8).toUpperCase()}: {saved.details}</p>}
    {!logs.length && <p>No checks recorded in this tab yet.</p>}
    <div className="cv-log-list" tabIndex={0} aria-label="Check history">{logs.map(log => <details key={log.id} className="cv-log-entry">
      <summary><time dateTime={new Date(log.startedAt).toISOString()}>{new Date(log.startedAt).toLocaleTimeString()}</time> · #{log.orderId.slice(-8).toUpperCase()} · {log.result}{log.finishedAt !== undefined ? ` · ${((log.finishedAt - log.startedAt) / 1000).toFixed(1)}s` : ""}</summary>
      <p>{log.trigger} · Revision {log.revision} · Attempt <code>{log.id}</code></p>
      <VisualDetails log={log} />
      <ol>{log.events.map((event, index) => <li key={index}><span>+{((event.at - log.startedAt) / 1000).toFixed(1)}s</span> {event.message}</li>)}</ol>
      {log.finishedAt === undefined && <small>No final result recorded yet; reloading during a check can leave an incomplete log.</small>}
    </details>)}</div>
  </section>;
}

function VisualDetails({ log }: { log: CvLog }) {
  const visual = photos.get(log.id);
  const diagnostic = visual?.diagnostics ?? log.diagnostics;
  const observation = diagnostic?.observations;
  const image = visual?.diagnostics?.image ?? visual?.capture;
  return <div className="cv-visuals">
    <div className="cv-photo-grid">
      <figure>{image ? <img src={image} alt="Captured order for this check" /> : <p>Photo unavailable after reload or history expiry.</p>}
        <figcaption>{visual?.diagnostics?.image ? "Order image sent to Perceptron" : "Browser capture · model input not available"}</figcaption></figure>
      {diagnostic?.references.map(ref => <figure key={ref.item_id}>
        {ref.image ? <img src={ref.image} alt={`Reference: ${ref.name}`} /> : <p>Reference image unavailable in this log.</p>}
        <figcaption>{ref.name} · {ref.role === "alternative" ? "Alternative" : "Expected item"} · v{ref.revision}</figcaption>
      </figure>)}
    </div>
    <strong>Perceptron reported</strong>
    {!observation ? <p>No valid model result recorded for this attempt.</p> : <>
      <table><thead><tr><th>Item</th><th>Expected</th><th>Observed</th><th>Result</th></tr></thead><tbody>
        {diagnostic?.targets.map(target => { const item = observation.targets.find(value => value.target_id === target.target_id); return <tr key={target.target_id}>
          <td>{target.name}{item?.reason && <small>{item.reason}</small>}{item?.label_text && <small>Label: {item.label_text}</small>}</td>
          <td>{target.expected_quantity}</td><td>{item?.observed_quantity ?? "Unknown"}</td><td>{item?.status ?? "Not reported"}</td>
        </tr>; })}
      </tbody></table>
      <p>Unexpected items: {observation.unexpected_items?.length ? observation.unexpected_items.map(item => `${item.quantity ?? "Unknown count"} × ${item.name}`).join(", ") : "None reported"}</p>
      {observation.scene_uncertainty && <p>Scene uncertainty: {observation.scene_uncertainty}</p>}
      {observation.provider && <small>{observation.provider.model} · {observation.provider.latency_ms} ms</small>}
      <details><summary>Structured model result</summary><pre>{JSON.stringify(observation, null, 2)}</pre></details>
    </>}
    <small>Model reports are separate from the final result above.</small>
  </div>;
}
