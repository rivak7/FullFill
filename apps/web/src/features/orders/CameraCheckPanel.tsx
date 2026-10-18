import { orderNumber } from "../../orderNumber";
import { preferredCamera } from "./preferredCamera";
import { readSettings } from "../../settings";
import { useEffect, useRef, useState } from "react";
import { orderApi, ApiError, type MenuPhoto } from "../../api/client";
import type { OrderState } from "../../api/generated/contracts";
import { SAMPLE_MS, SceneGuard, SceneTrigger } from "./sceneTrigger";
import { isFulfilled } from "./queueState";
import { CheckActivity, recordCheckAttempt } from "./CheckActivity";
import { cameraPhoto, cameraThumbnail } from "./cameraFraming";
import { CvLogs, attachCvVisuals, startCvLog, updateCvLog, checkResultDetails, sceneDiagnostic, type CheckTrigger } from "./CvLogs";

interface Props {
  order?: OrderState;
  workerId: string;
  disabled: boolean;
  pauseToken?: number;
  // Bumped by the kitchen's "Check now" button: take a photo of the mat right away.
  checkToken?: number;
  // `bagging` is true when the camera will watch this passed order get cleared off the mat.
  onResult: (state: OrderState, bagging: boolean) => void;
  onMatCleared?: (orderId: string) => void;
  onBusyChange: (busy: boolean) => void;
}

function sample(video: HTMLVideoElement): Uint8Array {
  const canvas = cameraThumbnail(video, 32);
  const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
  // RGB, dropping alpha: colour changes count, not just brightness.
  const rgb = new Uint8Array(data.length / 4 * 3);
  for (let i = 0; i < data.length / 4; i++) for (let c = 0; c < 3; c++) rgb[i * 3 + c] = data[i * 4 + c];
  return rgb;
}

export function CameraCheckPanel(props: Props) {
  const latest = useRef(props); latest.current = props;
  const ticketKey = props.order ? JSON.stringify([props.order.order.order_id, props.order.order.lines]) : "";
  const lastTicket = useRef("");
  const [handoff, setHandoff] = useState<"remove" | "place" | null>(null);
  const [tab, setTab] = useState<"camera" | "logs">("camera");
  const [open, setOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [automatic, setAutomatic] = useState(false);
  const automaticRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const chosenDevice = useRef("");
  const [lastPhoto, setLastPhoto] = useState<{ orderId: string; url: string } | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);
  const trigger = useRef(new SceneTrigger());
  // A passed order waiting for the mat to clear; the screen stays green until then.
  const bagging = useRef<string | null>(null);
  const guard = useRef<SceneGuard | null>(null);
  const interruptedByTab = useRef(false);
  // One unprompted look when automatic checks start, and one recheck after an amber
  // result. Green and red stand until the scene changes.
  const extraCheck = useRef<{ at: number; reason: CheckTrigger } | null>(null);

  function setAuto(value: boolean) {
    if (!value && bagging.current) { const held = bagging.current; bagging.current = null; latest.current.onMatCleared?.(held); }
    extraCheck.current = value ? { at: Date.now() + 5000, reason: "first look" } : null;
    automaticRef.current = value; setAutomatic(value); trigger.current.reset();
  }

  function stop() {
    guard.current?.invalidate("camera_stopped");
    generation.current++;
    stream.current?.getTracks().forEach(track => track.stop()); stream.current = null;
    if (video.current) video.current.srcObject = null;
    trigger.current.interrupt();
    setOpen(false); setReady(false); setAuto(false);
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void orderApi.cameraConfig(controller.signal).then(value => {
      if (!controller.signal.aborted) setConfigured(value.configured);
    }).catch(() => { if (!controller.signal.aborted) setConfigured(false); });
    const hidden = () => { if (document.hidden) {
      if (inFlight.current) interruptedByTab.current = true;
      guard.current?.invalidate("tab_hidden"); trigger.current.suspend();
    } };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      guard.current?.invalidate("page_closed");
      mounted.current = false; generation.current++; controller.abort();
      stream.current?.getTracks().forEach(track => track.stop());
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);

  useEffect(() => {
    guard.current?.invalidate("ticket_changed");
    if (lastTicket.current && lastTicket.current !== ticketKey) trigger.current.nextOrder();
    if (ticketKey) lastTicket.current = ticketKey;
    setHandoff(trigger.current.handoff);
  }, [ticketKey]);
  // A worker's override stands: drop any pending look or bagging watch. Auto-check
  // stays on, and only a changed mat starts the next check.
  useEffect(() => {
    if (bagging.current) { const held = bagging.current; bagging.current = null; latest.current.onMatCleared?.(held); }
    extraCheck.current = null; trigger.current.reset();
  }, [props.pauseToken]);
  useEffect(() => {
    if (!props.checkToken) return;
    if (!ready) setError("Turn on the camera to check this order.");
    else void checkRef.current("manual");
  }, [props.checkToken]);

  async function start(id = chosenDevice.current) {
    stop(); setError(""); setOpen(true); setAuto(true); trigger.current.learnEmptyMat();
    const current = generation.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access requires HTTPS and a supported browser.");
      const next = await preferredCamera(id, () => generation.current === current);
      if (!next) return;
      if (!mounted.current || generation.current !== current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next;
      next.getVideoTracks()[0]?.addEventListener("ended", () => { if (generation.current === current) { guard.current?.invalidate("camera_disconnected"); stop(); setError("Camera disconnected. Enable it to reconnect."); } });
      if (video.current) { video.current.srcObject = next; await video.current.play(); }
      const available = await navigator.mediaDevices.enumerateDevices().catch(() => []);
      if (mounted.current && generation.current === current) {
        setDevices(available.filter(device => device.kind === "videoinput"));
        setDeviceId(next.getVideoTracks()[0]?.getSettings().deviceId ?? id);
      }
    } catch (cause) {
      if (!mounted.current || generation.current !== current) return;
      stop(); setError(cause instanceof DOMException && cause.name === "NotAllowedError" ? "Allow camera access in your browser to continue." : "Could not open the camera. Check its connection and browser permissions.");
    }
  }

  async function check(source: CheckTrigger = "manual") {
    const { order, disabled } = latest.current;
    if (!order || disabled || isFulfilled(order) || inFlight.current || !video.current || !ready || !configured || document.hidden) return;
    const boundOrder = { id: order.order.order_id, revision: order.order.revision };
    const attemptId = crypto.randomUUID();
    startCvLog(attemptId, boundOrder.id, boundOrder.revision, source);
    let photo: MenuPhoto;
    let recheck = false;
    let retry = false;
    extraCheck.current = null;
    try {
      const frame = sample(video.current);
      photo = cameraPhoto(video.current);
      trigger.current.submitted(frame); setHandoff(null);
      guard.current = new SceneGuard();
    } catch { updateCvLog(attemptId, "Could not capture a camera frame; no request sent.", "Capture failed", true); setAuto(false); setError("Could not capture the image. Try reopening the camera."); return; }
    inFlight.current = true;
    interruptedByTab.current = false;
    attachCvVisuals(attemptId, { capture: `data:image/jpeg;base64,${photo.data_base64}` });
    setLastPhoto({ orderId: boundOrder.id, url: `data:image/jpeg;base64,${photo.data_base64}` });
    setBusy(true); setError("");
    latest.current.onBusyChange(true);
    recordCheckAttempt(attemptId);
    updateCvLog(attemptId, `Snapshot sent. Expected: ${order.order.lines.map(line => `${line.quantity}× ${line.name}`).join(", ")}.`, "Analyzing");
    try {
      const { boxes, photos } = readSettings();
      const sentAt = performance.now();
      const response = await orderApi.checkCamera({ worker_id: latest.current.workerId, order_id: boundOrder.id, expected_revision: boundOrder.revision, photo, boxes, photos, confirmed: true }, attemptId);
      const roundTrip = performance.now() - sentAt;
      if (response.diagnostics) attachCvVisuals(attemptId, { diagnostics: response.diagnostics });
      const steps = response.diagnostics?.timings_ms;
      // Whatever the server didn't spend is upload, download and function start-up.
      if (steps) updateCvLog(attemptId, `Server steps: ${[...Object.entries(steps), ["network", roundTrip - Object.values(steps).reduce((a, b) => a + b, 0)] as const].map(([step, ms]) => `${step.replace("_", " ")} ${(Math.max(0, ms) / 1000).toFixed(1)} s`).join(", ")}.`);
      let state: OrderState = response;
      updateCvLog(attemptId, `Server response: ${checkResultDetails(state)}. Check ID: ${state.current_check?.check_id ?? "none"}.`);
      const validateScene = () => {
        if (!mounted.current) guard.current?.invalidate("page_closed");
        else if (document.hidden) guard.current?.invalidate("tab_hidden");
        else if (!video.current || !stream.current?.active) guard.current?.invalidate("camera_unavailable");
        return guard.current?.unchanged() ?? false;
      };
      // The server completes the check straight away (one round trip); the browser
      // only calls confirm to withdraw it when the photo no longer belongs to this
      // screen, or for a server that still waits for confirmation.
      const awaiting = state.current_check?.execution_status === "awaiting_confirmation";
      const withdraw = state.current_check?.execution_status === "completed" && !validateScene();
      if (mounted.current && (awaiting || withdraw)) {
        const confirm = (unchanged: boolean) => orderApi.confirmCamera({ worker_id: latest.current.workerId, order_id: boundOrder.id, check_id: state.current_check!.check_id, expected_revision: state.order.revision, scene_unchanged: unchanged });
        const unchanged = !withdraw && validateScene();
        updateCvLog(attemptId, unchanged ? "Confirming result." : `Result invalidated by browser: ${sceneDiagnostic(guard.current?.reason)}.`, "Confirming");
        const confirmAt = performance.now();
        state = await confirm(unchanged);
        updateCvLog(attemptId, `Confirmed in ${((performance.now() - confirmAt) / 1000).toFixed(1)} s.`);
      }
      recheck = source !== "recheck after amber" && state.current_check?.execution_status === "completed" && state.current_check.verdict === "unsure";
      updateCvLog(attemptId, checkResultDetails(state), state.current_check?.execution_status === "completed" ? state.current_check.verdict === "pass" ? "Fulfilled" : state.current_check.verdict === "fail" ? "Unfulfilled" : "Needs review" : state.current_check?.execution_status ?? "No result", true);
      if (mounted.current) {
        const watching = automaticRef.current && !!stream.current?.active && isFulfilled(state);
        if (watching) { bagging.current = boundOrder.id; trigger.current.nextOrder(); setHandoff(trigger.current.handoff); }
        latest.current.onResult(state, watching);
        if (state.current_check?.execution_status !== "completed") {
          const resume = interruptedByTab.current && automaticRef.current
            && state.current_check?.execution_status === "superseded"
            && state.current_check.error_code !== "reference_changed"
            && latest.current.order?.order.order_id === boundOrder.id;
          if (resume) { trigger.current.retryInterrupted(); setError(""); }
          else {
            setError(state.current_check?.error_code === "reference_changed" ? "Menu reference photos changed. Press Check now." : state.current_check?.execution_status === "superseded" ? "The view changed during the check. Keep the order still and press Check now." : "The check has not completed. Press Check now to try again.");
          }
        }
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.diagnostics) attachCvVisuals(attemptId, { diagnostics: cause.diagnostics });
      const status = cause && typeof cause === "object" && "status" in cause && typeof cause.status === "number" ? `HTTP ${cause.status}: ` : "";
      if (cause instanceof ApiError && cause.diagnostics?.raw_answer) updateCvLog(attemptId, `Perceptron answered: ${cause.diagnostics.raw_answer}`);
      // One fresh photo after a failed call (server or network trouble, an answer we
      // couldn't read). A rejected request (4xx) would only fail the same way again.
      retry = automaticRef.current && source !== "retry after error" && !(cause instanceof ApiError && cause.status < 500);
      updateCvLog(attemptId, status + (cause instanceof Error ? cause.message : "Request failed") + (retry ? " Retrying once with a new photo." : ""), "Request failed", true);
      // Auto-check stays on; the next change on the mat (or Check now) starts a new check.
      if (mounted.current && !retry) setError(cause instanceof Error ? cause.message : "Check failed. Press Check now to try again.");
    } finally {
      if (recheck) extraCheck.current = { at: Date.now() + 5000, reason: "recheck after amber" };
      if (retry) extraCheck.current = { at: Date.now() + 1500, reason: "retry after error" };
      guard.current = null;
      inFlight.current = false;
      if (mounted.current) { setBusy(false); latest.current.onBusyChange(false); }
    }
  }
  const checkRef = useRef(check); checkRef.current = check;

  useEffect(() => {
    if (!open || !ready) return;
    const timer = window.setInterval(() => {
      if (inFlight.current) {
        if (document.hidden) guard.current?.invalidate("tab_hidden");
        else if (!video.current || !stream.current?.active) guard.current?.invalidate("camera_unavailable");
        return;
      }
      if (!video.current || document.hidden || !stream.current?.active) return;
      const { order, disabled } = latest.current;
      try {
        // Keep observing handoffs while a claim is loading or the queue is empty.
        const now = Date.now();
        const extra = extraCheck.current && now >= extraCheck.current.at ? extraCheck.current.reason : null;
        const settled = trigger.current.sample(sample(video.current), now, extra !== null);
        setHandoff(trigger.current.handoff);
        if (bagging.current && trigger.current.handoff === "place") {
          const cleared = bagging.current; bagging.current = null;
          latest.current.onMatCleared?.(cleared);
        }
        if (settled && automaticRef.current && order && !disabled && !isFulfilled(order)) void checkRef.current(trigger.current.handoff ? "next order" : extra ?? "scene change");
      } catch { setAuto(false); trigger.current.interrupt(); setError("Camera processing stopped. Reopen the camera to continue."); }
    }, SAMPLE_MS);
    return () => window.clearInterval(timer);
  }, [open, ready]);

  const status = busy ? "Checking… hold still" : !ready ? "Opening camera…" : automatic && handoff === "remove" ? "Bag it and clear the mat" : automatic && handoff === "place" ? "Place the next order" : automatic ? null : "Paused · reopen the camera";
  return <section className={`camera-check ${open ? "camera-check-open" : ""}`} aria-label="Camera check" data-auto={automatic ? "on" : "off"}>
    <div className="dock-bar">
      <div className="cv-tabs" role="tablist" aria-label="Camera and diagnostics">
        <button type="button" role="tab" id="camera-tab" aria-controls="camera-panel" aria-selected={tab === "camera"} onClick={() => setTab("camera")}>Camera</button>
        <button type="button" role="tab" id="logs-tab" aria-controls="logs-panel" aria-selected={tab === "logs"} onClick={() => setTab("logs")}>CV logs</button>
      </div>
      {open && <button className="text-button" onClick={stop}>Turn off camera</button>}
    </div>
    <div role="tabpanel" id="camera-panel" aria-labelledby="camera-tab" hidden={tab !== "camera"}>
    {open ? <div className="camera-check-body">
      <div className={`camera-frame${busy ? " camera-frame-busy" : ""}`}>
        <video className="camera-preview" ref={video} autoPlay playsInline muted aria-label="Packing area camera preview" onLoadedData={() => setReady(true)} />
        <span className={`camera-state${busy ? " camera-state-busy" : ""}`} role="status" hidden={!status}>{status}</span>
      </div>
      <div className="camera-check-controls">
        {devices.length > 1 && <select aria-label="Camera" value={deviceId} onChange={event => { chosenDevice.current = event.target.value; setDeviceId(event.target.value); void start(event.target.value); }}>{devices.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label || "Camera"}</option>)}</select>}
        {lastPhoto && <details className="camera-last-photo"><summary>Last photo · #{orderNumber(lastPhoto.orderId)}</summary><img src={lastPhoto.url} alt={`Last submitted camera photo for order ${orderNumber(lastPhoto.orderId)}`} /></details>}
      </div>
    </div> : <div className="camera-off">
      <svg viewBox="0 0 48 48" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="13" width="38" height="27" rx="7" /><path d="M17 13l3-5h8l3 5" /><circle cx="24" cy="26" r="7" /></svg>
      <p>Turn on the camera so FullFill can watch the mat.</p>
      <button className="primary-button" onClick={() => void start()}>Enable camera</button>
    </div>}
    </div>
    <div role="tabpanel" id="logs-panel" aria-labelledby="logs-tab" hidden={tab !== "logs"}><CheckActivity /><CvLogs order={props.order} /></div>
    {configured === false && <p className="camera-hint">AI checks unavailable. Camera preview still works.</p>}
    {error && <p role="alert" className="error-banner">{error}</p>}
  </section>;
}
