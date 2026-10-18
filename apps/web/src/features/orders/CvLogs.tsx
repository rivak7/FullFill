import { orderNumber } from "../../orderNumber";
import { useEffect, useState } from "react";
import { AnnotatedPhoto } from "./AnnotatedPhoto";
import type { CameraDiagnostics } from "../../api/client";
import type { OrderState } from "../../api/generated/contracts";

export type CheckTrigger = "manual" | "scene change" | "first look" | "recheck after amber" | "retry after error" | "next order";
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

// One plain line per result: the color first, then what the checker said.
export function checkResultDetails(state: OrderState): string {
  const check = state.current_check;
  if (!check) return "No check";
  const messages = check.discrepancies?.map(item => item.message) ?? [];
  const color = check.execution_status !== "completed" ? null : check.verdict === "pass" ? "Green" : check.verdict === "fail" ? "Red" : "Amber";
  const head = color ?? `${check.execution_status[0].toUpperCase()}${check.execution_status.slice(1).replace(/_/g, " ")}${check.error_code ? ` (${check.error_code})` : ""}`;
  return [head, ...messages].join(" · ");
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
  return reason && labels[reason] ? `${labels[reason]} (${reason})` : reason ?? "unknown";
}

function resultTone(result: string): string {
  if (result === "Fulfilled") return "green";
  if (result === "Unfulfilled") return "red";
  if (result === "Needs review") return "amber";
  return ["Capturing", "Analyzing", "Confirming"].includes(result) ? "running" : "error";
}

const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`;
const modelMs = (log: CvLog) => (photos.get(log.id)?.diagnostics ?? log.diagnostics)?.observations?.provider?.latency_ms;

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
    catch { setCopyStatus("Could not copy. Select the text below instead."); }
  }
  return <section className="cv-logs" aria-label="CV logs">
    <div className="cv-log-actions">
      <span className="cv-log-caption">Last 50 checks in this tab</span>
      <span role="status">{copyStatus}</span>
      <button type="button" className="secondary-button" onClick={() => void copy()}>Copy logs</button>
      <button type="button" className="secondary-button" disabled={!logs.length} onClick={() => { photos.clear(); save([]); setCopyStatus(""); }}>Clear logs</button>
    </div>
    {!logs.length && <p className="cv-log-empty">No checks yet.</p>}
    <div className="cv-log-list" tabIndex={0} aria-label="Check history">{logs.map(log => <details key={log.id} className={`cv-log-entry cv-tone-${resultTone(log.result)}`}>
      <summary>
        <span className="cv-chip">{log.result}</span>
        <strong>#{orderNumber(log.orderId)}</strong>
        <span className="cv-log-trigger">{log.trigger[0].toUpperCase() + log.trigger.slice(1)}</span>
        <span className="cv-log-time"><time dateTime={new Date(log.startedAt).toISOString()}>{new Date(log.startedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}</time>{log.finishedAt !== undefined && ` · ${seconds(log.finishedAt - log.startedAt)}`}{modelMs(log) !== undefined && ` (model ${seconds(modelMs(log)!)})`}</span>
      </summary>
      <div className="cv-log-body">
        <VisualDetails log={log} />
        <h4>Steps</h4>
        <ol className="cv-steps">{log.events.map((event, index) => <li key={index}><span>+{seconds(event.at - log.startedAt)}</span>{event.message}</li>)}</ol>
        {log.finishedAt === undefined && <small>No final result yet. Reloading during a check leaves the log unfinished.</small>}
        <RawDetails log={log} />
      </div>
    </details>)}</div>
  </section>;
}

function VisualDetails({ log }: { log: CvLog }) {
  const visual = photos.get(log.id);
  const diagnostic = visual?.diagnostics ?? log.diagnostics;
  const observation = diagnostic?.observations;
  const image = visual?.diagnostics?.image ?? visual?.capture;
  // Older logs and failed requests may have no diagnostics; the steps below say what happened.
  if (!diagnostic && !image) return null;
  return <div className="cv-visuals">
    <h4>What Perceptron saw</h4>
    {!observation ? <p className="cv-muted">No model result for this check.</p> : <>
      <table><thead><tr><th>Item</th><th>Want</th><th>Saw</th><th>Result</th></tr></thead><tbody>
        {diagnostic?.targets.map(target => { const item = observation.targets.find(value => value.target_id === target.target_id); return <tr key={target.target_id}>
          <td>{target.name}{item?.reason && <small>{item.reason}</small>}{item?.label_text && <small>Label: {item.label_text}</small>}</td>
          <td>{target.expected_quantity}</td><td>{item?.observed_quantity ?? "?"}</td><td><span className={`cv-status cv-status-${item?.status ?? "none"}`}>{item?.status ?? "Not reported"}</span></td>
        </tr>; })}
      </tbody></table>
      {!!observation.unexpected_items?.length && <p>Not on ticket: {observation.unexpected_items.map(item => `${item.quantity ?? "?"} × ${item.name}`).join(", ")}</p>}
      {observation.scene_uncertainty && <p>Scene: {observation.scene_uncertainty}</p>}
    </>}
    <div className="cv-photo-grid">
      <figure>{image ? <AnnotatedPhoto image={image} observations={observation} targets={diagnostic?.targets} modelInput={!!visual?.diagnostics?.image} /> : <p className="cv-muted">Photo gone after reload.</p>}
        <figcaption>{visual?.diagnostics?.image ? "Sent to Perceptron" : "Browser capture"}</figcaption></figure>
      {diagnostic?.references.map(ref => <figure key={ref.item_id}>
        {ref.image ? <img src={ref.image} alt={`Reference: ${ref.name}`} /> : <p className="cv-muted">No reference image in this log.</p>}
        <figcaption>{ref.name}{ref.role === "alternative" ? " · lookalike" : ""}</figcaption>
      </figure>)}
    </div>
  </div>;
}

function RawDetails({ log }: { log: CvLog }) {
  const observation = (photos.get(log.id)?.diagnostics ?? log.diagnostics)?.observations;
  return <details className="cv-raw">
    <summary>Details</summary>
    <dl className="cv-model-stats">
      {observation?.provider && <>
        <div><dt>Model</dt><dd>{observation.provider.model}</dd></div>
        <div><dt>Model time</dt><dd>{(observation.provider.latency_ms / 1000).toFixed(2)} s</dd></div>
        <div><dt>Reasoning</dt><dd>{/reasoning-(\w+)/.exec(observation.provider.prompt_version)?.[1] ?? "none"}</dd></div>
        <div><dt>Input tokens</dt><dd>{observation.provider.prompt_tokens?.toLocaleString() ?? "Unavailable"}</dd></div>
        <div><dt>Output tokens</dt><dd>{observation.provider.completion_tokens?.toLocaleString() ?? "Unavailable"}</dd></div>
      </>}
      <div><dt>Revision</dt><dd>{log.revision}</dd></div>
      <div><dt>Attempt</dt><dd><code>{log.id}</code></dd></div>
    </dl>
    {observation && <pre>{JSON.stringify(observation, null, 2)}</pre>}
  </details>;
}
