import { useEffect, useRef, useState } from "react";
import { orderApi, type MenuPhoto } from "../../api/client";
import type { OrderState } from "../../api/generated/contracts";
import { SceneGuard, SceneTrigger } from "./sceneTrigger";
import { isFulfilled } from "./queueState";
import { CheckActivity, recordCheckAttempt } from "./CheckActivity";
import { cameraConstraints, cameraPhoto, cropCamera } from "./cameraFraming";
import { CvLogs, startCvLog, updateCvLog, checkResultDetails, sceneDiagnostic, type CheckTrigger } from "./CvLogs";

interface Props {
  order?: OrderState;
  workerId: string;
  disabled: boolean;
  pauseToken?: number;
  onResult: (state: OrderState) => void;
  onBusyChange: (busy: boolean) => void;
}

function sample(video: HTMLVideoElement): Uint8Array {
  const canvas = cropCamera(video, 32);
  const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
  const gray = new Uint8Array(data.length / 4);
  for (let i = 0; i < gray.length; i++) gray[i] = (data[i * 4] + data[i * 4 + 1] + data[i * 4 + 2]) / 3;
  return gray;
}

export function CameraCheckPanel(props: Props) {
  const latest = useRef(props); latest.current = props;
  const ticketKey = props.order ? JSON.stringify([props.order.order.order_id, props.order.order.lines]) : "";
  const lastTicket = useRef("");
  const [handoff, setHandoff] = useState<"remove" | "place" | null>(null);
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
  const [lastPhoto, setLastPhoto] = useState<{ orderId: string; url: string } | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);
  const trigger = useRef(new SceneTrigger());
  const guard = useRef<SceneGuard | null>(null);
  const interruptedByTab = useRef(false);
  const nextPeriodicCheck = useRef(0);

  function setAuto(value: boolean) {
    if (value) nextPeriodicCheck.current = Date.now() + 5000;
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
  useEffect(() => { setAuto(false); }, [props.pauseToken]);

  async function start(id = deviceId) {
    stop(); setError(""); setOpen(true); setAuto(true);
    const current = generation.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access requires HTTPS and a supported browser.");
      const next = await navigator.mediaDevices.getUserMedia(cameraConstraints(id));
      if (!mounted.current || generation.current !== current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next;
      next.getVideoTracks()[0]?.addEventListener("ended", () => { if (generation.current === current) { guard.current?.invalidate("camera_disconnected"); stop(); setError("Camera disconnected. Enable it to reconnect."); } });
      if (video.current) { video.current.srcObject = next; await video.current.play(); }
      const available = await navigator.mediaDevices.enumerateDevices();
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
    try {
      const frame = sample(video.current);
      photo = cameraPhoto(video.current);
      trigger.current.submitted(frame); setHandoff(null);
      guard.current = new SceneGuard(frame, Date.now());
    } catch { updateCvLog(attemptId, "Could not capture a camera frame; no request sent.", "Capture failed", true); setAuto(false); setError("Could not capture the image. Try reopening the camera."); return; }
    inFlight.current = true;
    interruptedByTab.current = false;
    setLastPhoto({ orderId: boundOrder.id, url: `data:image/jpeg;base64,${photo.data_base64}` });
    setBusy(true); setError("");
    latest.current.onBusyChange(true);
    recordCheckAttempt(attemptId);
    updateCvLog(attemptId, `Snapshot sent. Expected: ${order.order.lines.map(line => `${line.quantity}× ${line.name}`).join(", ")}.`, "Analyzing");
    try {
      let state = await orderApi.checkCamera({ worker_id: latest.current.workerId, order_id: boundOrder.id, expected_revision: boundOrder.revision, photo }, attemptId);
      updateCvLog(attemptId, `Server response: ${checkResultDetails(state)}. Check ID: ${state.current_check?.check_id ?? "none"}.`);
      const validateScene = () => {
        if (!mounted.current) guard.current?.invalidate("page_closed");
        else if (document.hidden) guard.current?.invalidate("tab_hidden");
        else if (!video.current || !stream.current?.active) guard.current?.invalidate("camera_unavailable");
        else { try { guard.current?.sample(sample(video.current), Date.now()); } catch { guard.current?.invalidate("capture_error"); } }
        return guard.current?.unchanged(Date.now()) ?? false;
      };
      if (mounted.current && state.current_check?.execution_status === "awaiting_confirmation") {
        const confirm = (unchanged: boolean) => orderApi.confirmCamera({ worker_id: latest.current.workerId, order_id: boundOrder.id, check_id: state.current_check!.check_id, expected_revision: state.order.revision, scene_unchanged: unchanged });
        const unchanged = validateScene();
        updateCvLog(attemptId, unchanged ? "View unchanged; confirming result." : `Result invalidated by browser: ${sceneDiagnostic(guard.current?.reason)}.`, "Confirming");
        state = await confirm(unchanged);
        // Movement during the final network write also revokes this same result.
        if (unchanged && !validateScene() && state.current_check?.execution_status === "completed") {
          updateCvLog(attemptId, `View invalidated during confirmation: ${sceneDiagnostic(guard.current?.reason)}. Revoking result.`);
          state = await confirm(false);
        }
      }
      updateCvLog(attemptId, checkResultDetails(state), state.current_check?.execution_status === "completed" ? state.current_check.verdict === "pass" ? "Fulfilled" : state.current_check.verdict === "fail" ? "Unfulfilled" : "Needs review" : state.current_check?.execution_status ?? "No result", true);
      if (mounted.current) {
        latest.current.onResult(state);
        if (state.current_check?.execution_status !== "completed") {
          const resume = interruptedByTab.current && automaticRef.current
            && state.current_check?.execution_status === "superseded"
            && state.current_check.error_code !== "reference_changed"
            && latest.current.order?.order.order_id === boundOrder.id;
          if (resume) { trigger.current.retryInterrupted(); setError(""); }
          else {
            setAuto(false); setError(state.current_check?.error_code === "reference_changed" ? "Menu reference photos changed. Take a new photo." : state.current_check?.execution_status === "superseded" ? "The view changed during the check. Keep the order still and take a new photo." : "The check has not completed. Check manually before starting another.");
          }
        }
      }
    } catch (cause) {
      const status = cause && typeof cause === "object" && "status" in cause && typeof cause.status === "number" ? `HTTP ${cause.status}: ` : "";
      updateCvLog(attemptId, status + (cause instanceof Error ? cause.message : "Request failed"), "Request failed", true);
      if (mounted.current) { setAuto(false); setError(cause instanceof Error ? cause.message : "Check failed. Try again manually."); }
    } finally {
      nextPeriodicCheck.current = Date.now() + 5000;
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
        try {
          if (document.hidden) guard.current?.invalidate("tab_hidden");
          else if (!video.current || !stream.current?.active) guard.current?.invalidate("camera_unavailable");
          else guard.current?.sample(sample(video.current), Date.now());
        } catch { guard.current?.invalidate("capture_error"); }
        return;
      }
      if (!video.current || document.hidden || !stream.current?.active) return;
      const { order, disabled } = latest.current;
      try {
        // Keep observing handoffs while a claim is loading or the queue is empty.
        const now = Date.now();
        const settled = trigger.current.sample(sample(video.current), now, now >= nextPeriodicCheck.current);
        setHandoff(trigger.current.handoff);
        if (settled && automaticRef.current && order && !disabled && !isFulfilled(order)) void checkRef.current(trigger.current.handoff ? "next order" : now >= nextPeriodicCheck.current ? "periodic" : "scene change");
      } catch { setAuto(false); trigger.current.interrupt(); setError("Camera processing stopped. Reopen the camera to continue."); }
    }, 250);
    return () => window.clearInterval(timer);
  }, [open, ready]);

  const canCheck = ready && configured && !!props.order && !isFulfilled(props.order) && !props.disabled && !busy;
  return <section className={`camera-check ${open ? "camera-check-open" : ""}`} aria-label="Camera check">
    <div className="camera-check-heading"><strong>Camera check</strong>{open ? <button className="secondary-button" onClick={stop}>Close camera</button> : <button className="secondary-button" onClick={() => void start()}>Enable camera</button>}</div>
    {open && <div className="camera-check-body">
      <video className="camera-preview" ref={video} autoPlay playsInline muted aria-label="Packing area camera preview" onLoadedData={() => setReady(true)} />
      <div className="camera-check-controls">
        {devices.length > 1 && <label>Camera<select aria-label="Camera" value={deviceId} onChange={event => { setDeviceId(event.target.value); void start(event.target.value); }}>{devices.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label || "Camera"}</option>)}</select></label>}
        <p role="status">{busy ? "Checking… keep the order in place." : !ready ? "Opening camera…" : automatic && handoff === "remove" ? "Remove the previous order from view." : automatic && handoff === "place" ? "Place the next order in view. Checking starts when it settles." : automatic ? "Place the order in view. Checking starts when it settles." : "Automatic checks paused. Check manually or turn them back on."}</p>
        <button className="primary-button" disabled={!canCheck} onClick={() => void check()}>{busy ? "Checking…" : "Check order"}</button>
        <label className="camera-auto"><input type="checkbox" checked={automatic} disabled={!ready || !configured} onChange={event => setAuto(event.target.checked)} />Automatic checks</label>
        {automatic && <small>Rechecks a still view every 5 seconds after the previous check finishes.</small>}
        {props.order?.current_check?.verdict === "unsure" && <p>Inspect the highlighted items, then recheck or fulfill manually.</p>}
      </div>
      {lastPhoto && <details className="camera-last-photo"><summary>Last photo · #{lastPhoto.orderId.slice(-8).toUpperCase()}</summary><img src={lastPhoto.url} alt={`Last submitted camera photo for order ${lastPhoto.orderId.slice(-8).toUpperCase()}`} /><small>Snapshot used for the check. Kept only in this page.</small></details>}
    </div>}
    <CheckActivity />
    <CvLogs order={props.order} />
    {configured === false && <p className="camera-hint">AI checks unavailable. Camera preview still works.</p>}
    {error && <p role="alert" className="error-banner">{error}</p>}
  </section>;
}
