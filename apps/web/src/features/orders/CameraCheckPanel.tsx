import { useEffect, useRef, useState } from "react";
import { orderApi, type MenuPhoto } from "../../api/client";
import type { OrderState } from "../../api/generated/contracts";
import { SceneTrigger } from "./sceneTrigger";
import { isFulfilled } from "./queueState";

interface Props {
  order?: OrderState;
  disabled: boolean;
  onResult: (state: OrderState) => void;
  onBusyChange: (busy: boolean) => void;
}

function crop(video: HTMLVideoElement, width: number): HTMLCanvasElement {
  if (!video.videoWidth || !video.videoHeight) throw new Error("Wait for the camera image.");
  // The preview uses this same centered square, so the worker sees exactly what is sent.
  const side = Math.min(video.videoWidth, video.videoHeight);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = Math.min(width, side);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser cannot capture the camera.");
  context.drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2, side, side, 0, 0, canvas.width, canvas.height);
  return canvas;
}

function sample(video: HTMLVideoElement): Uint8Array {
  const canvas = crop(video, 32);
  const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
  const gray = new Uint8Array(data.length / 4);
  for (let i = 0; i < gray.length; i++) gray[i] = (data[i * 4] + data[i * 4 + 1] + data[i * 4 + 2]) / 3;
  return gray;
}

export function CameraCheckPanel(props: Props) {
  const latest = useRef(props); latest.current = props;
  const [open, setOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [automatic, setAutomatic] = useState(false);
  const automaticRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const [used, setUsed] = useState(0);
  const calls = useRef(0);
  const [cooldown, setCooldown] = useState(false);
  const nextCheck = useRef(0);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);
  const trigger = useRef(new SceneTrigger());

  function setAuto(value: boolean) {
    automaticRef.current = value; setAutomatic(value); trigger.current.reset();
  }

  function stop() {
    generation.current++;
    stream.current?.getTracks().forEach(track => track.stop()); stream.current = null;
    if (video.current) video.current.srcObject = null;
    setOpen(false); setReady(false); setAuto(false);
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void orderApi.cameraConfig(controller.signal).then(value => {
      if (!controller.signal.aborted) setConfigured(value.configured);
    }).catch(() => { if (!controller.signal.aborted) setConfigured(false); });
    const hidden = () => { if (document.hidden) { setAuto(false); trigger.current.reset(); } };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      mounted.current = false; generation.current++; controller.abort();
      stream.current?.getTracks().forEach(track => track.stop());
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);

  useEffect(() => { trigger.current.reset(); }, [props.order?.order.order_id]);

  async function start(id = deviceId) {
    stop(); setError(""); setOpen(true);
    const current = generation.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access requires HTTPS and a supported browser.");
      const next = await navigator.mediaDevices.getUserMedia({ audio: false, video: { ...(id ? { deviceId: { exact: id } } : { facingMode: { ideal: "environment" } }), width: { ideal: 1280 }, height: { ideal: 960 } } });
      if (!mounted.current || generation.current !== current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next;
      next.getVideoTracks()[0]?.addEventListener("ended", () => { if (generation.current === current) { stop(); setError("Camera disconnected. Enable it to reconnect."); } });
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

  async function check() {
    const { order, disabled } = latest.current;
    if (!order || disabled || isFulfilled(order) || inFlight.current || !video.current || !ready || !configured || calls.current >= 10 || Date.now() < nextCheck.current || document.hidden) return;
    const boundOrder = { id: order.order.order_id, revision: order.order.revision };
    let photo: MenuPhoto;
    try {
      const frame = sample(video.current);
      photo = { data_base64: crop(video.current, 1024).toDataURL("image/jpeg", 0.8).split(",")[1] };
      if (photo.data_base64.length > 1_800_000) throw new Error("Camera image is too large.");
      trigger.current.submitted(frame, Date.now());
    } catch { setAuto(false); setError("Could not capture the image. Try reopening the camera."); return; }
    inFlight.current = true; calls.current++; nextCheck.current = Date.now() + 10000;
    setUsed(calls.current); setBusy(true); setCooldown(true); setError("");
    latest.current.onBusyChange(true);
    if (calls.current >= 10) setAuto(false);
    try {
      const state = await orderApi.checkCamera({ order_id: boundOrder.id, expected_revision: boundOrder.revision, photo }, crypto.randomUUID());
      if (mounted.current) {
        latest.current.onResult(state);
        if (state.current_check?.execution_status !== "completed") {
          setAuto(false); setError("The check has not completed. Check manually before starting another.");
        }
      }
    } catch (cause) {
      if (mounted.current) { setAuto(false); setError(cause instanceof Error ? cause.message : "Check failed. Try again manually."); }
    } finally {
      inFlight.current = false; nextCheck.current = Date.now() + 10000;
      if (mounted.current) { setBusy(false); latest.current.onBusyChange(false); }
    }
  }
  const checkRef = useRef(check); checkRef.current = check;

  useEffect(() => {
    if (!open || !ready) return;
    const timer = window.setInterval(() => {
      setCooldown(Date.now() < nextCheck.current);
      if (!video.current || document.hidden || !automaticRef.current || inFlight.current) return;
      const { order, disabled } = latest.current;
      if (!order || disabled || isFulfilled(order)) { trigger.current.reset(); return; }
      try { if (trigger.current.sample(sample(video.current), Date.now())) void checkRef.current(); }
      catch { setAuto(false); setError("Camera processing stopped. Reopen the camera to continue."); }
    }, 250);
    return () => window.clearInterval(timer);
  }, [open, ready]);

  const canCheck = ready && configured && !!props.order && !isFulfilled(props.order) && !props.disabled && !busy && !cooldown && used < 10;
  return <section className={`camera-check ${open ? "camera-check-open" : ""}`} aria-label="Camera check">
    <div className="camera-check-heading"><strong>Camera check</strong>{open ? <button className="secondary-button" onClick={stop}>Close camera</button> : <button className="secondary-button" onClick={() => void start()}>Enable camera</button>}</div>
    {open && <div className="camera-check-body">
      <video ref={video} autoPlay playsInline muted aria-label="Packing area camera preview" onLoadedData={() => setReady(true)} />
      <div className="camera-check-controls">
        {devices.length > 1 && <label>Camera<select aria-label="Camera" value={deviceId} onChange={event => { setDeviceId(event.target.value); void start(event.target.value); }}>{devices.map(device => <option key={device.deviceId} value={device.deviceId}>{device.label || "Camera"}</option>)}</select></label>}
        <p>{busy ? "Checking this ticket…" : !ready ? "Opening camera…" : "Keep all items inside the preview."}</p>
        <button className="primary-button" disabled={!canCheck} onClick={() => void check()}>{busy ? "Checking…" : cooldown ? "Wait before checking again" : "Check order"}</button>
        <label className="camera-auto"><input type="checkbox" checked={automatic} disabled={!ready || !configured || used >= 10} onChange={event => setAuto(event.target.checked)} />Auto check after movement</label>
        <small>{used}/10 checks this session · Preview is free</small>
        {used >= 10 && <p>Session limit reached. Continue with manual fulfillment.</p>}
      </div>
    </div>}
    {configured === false && <p className="camera-hint">AI checks unavailable. Camera preview still works.</p>}
    {error && <p role="alert" className="error-banner">{error}</p>}
  </section>;
}
