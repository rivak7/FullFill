import { useEffect, useRef, useState } from "react";
import type { MenuPhoto } from "../../api/client";

function photoFrom(source: CanvasImageSource, width: number, height: number): MenuPhoto {
  if (!width || !height) throw new Error("The photo isn't ready yet. Try again.");
  const scale = Math.min(1, 1920 / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser couldn't prepare the photo.");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  // Re-encoding also removes camera metadata. Keep JSON well below Vercel's limit.
  for (const quality of [0.9, 0.8, 0.65, 0.5]) {
    const data = canvas.toDataURL("image/jpeg", quality).split(",")[1];
    if (data && data.length <= 1_800_000) return { data_base64: data };
  }
  throw new Error("This photo is too large. Try a smaller photo.");
}

export function MenuPhotoPicker({ photo, savedUrl, disabled, onChange, onBusyChange }: {
  photo?: MenuPhoto;
  savedUrl: string | null;
  disabled: boolean;
  onChange: (photo: MenuPhoto | undefined) => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const [cameraOpen, setCameraOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const preview = photo ? `data:image/jpeg;base64,${photo.data_base64}` : savedUrl;

  function stopCamera() {
    generation.current++;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setCameraOpen(false); setReady(false);
  }

  useEffect(() => { onBusyChange(cameraOpen || preparing); }, [cameraOpen, preparing, onBusyChange]);
  useEffect(() => () => {
    generation.current++;
    stream.current?.getTracks().forEach(track => track.stop());
  }, []);

  async function openCamera(id = deviceId) {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Camera access needs HTTPS and a supported browser. You can upload a photo instead."); return;
    }
    const current = ++generation.current;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setCameraOpen(true); setReady(false);
    try {
      const next = await navigator.mediaDevices.getUserMedia({ audio: false, video: { ...(id ? { deviceId: { exact: id } } : { facingMode: { ideal: "environment" } }), width: { ideal: 1920 } } });
      if (generation.current !== current) { next.getTracks().forEach(track => track.stop()); return; }
      stream.current = next;
      setDeviceId(next.getVideoTracks()[0]?.getSettings().deviceId ?? id);
      if (video.current) { video.current.srcObject = next; await video.current.play(); }
      // Listing cameras is optional; a working preview should survive a listing failure.
      try {
        const available = await navigator.mediaDevices.enumerateDevices();
        if (generation.current === current) setDevices(available.filter(device => device.kind === "videoinput"));
      } catch { /* Keep the active camera available for capture. */ }
    } catch (error) {
      if (generation.current !== current) return;
      stopCamera();
      setError(error instanceof DOMException && error.name === "NotAllowedError"
        ? "Camera access was denied. Allow it in your browser or upload a photo."
        : "Couldn't open the camera. Check that it isn't in use, or upload a photo.");
    }
  }

  function capture() {
    if (!video.current) return;
    try {
      onChange(photoFrom(video.current, video.current.videoWidth, video.current.videoHeight));
      stopCamera(); setError(null);
    } catch (error) { setError(error instanceof Error ? error.message : "Couldn't take the photo."); }
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 20_000_000) {
      setError("Choose a JPEG, PNG, or WebP photo up to 20 MB."); return;
    }
    setPreparing(true);
    const current = ++generation.current;
    const url = URL.createObjectURL(file);
    try {
      const image = new Image(); image.src = url; await image.decode();
      if (generation.current === current) onChange(photoFrom(image, image.naturalWidth, image.naturalHeight));
    } catch { if (generation.current === current) setError("Couldn't read that photo. Try a different JPEG or PNG."); }
    finally { URL.revokeObjectURL(url); if (generation.current === current) setPreparing(false); }
  }

  return <div className="menu-photo-picker">
    <div className="photo-label"><span>Photo</span><span>{preview ? "" : "Required for new items"}</span></div>
    {cameraOpen ? <div className="camera-panel">
      {devices.length > 1 && <label>Camera<select aria-label="Menu photo camera" value={deviceId} disabled={disabled} onChange={event => { setDeviceId(event.target.value); void openCamera(event.target.value); }}>{devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Camera ${index + 1}`}</option>)}</select></label>}
      <video ref={video} autoPlay playsInline muted onLoadedData={() => setReady(true)} aria-label="Menu item camera preview" />
      {!ready && <p role="status">Opening camera…</p>}
      <div className="photo-actions"><button type="button" className="secondary-button" onClick={stopCamera}>Close camera</button><button type="button" className="primary-button" disabled={!ready || disabled} onClick={capture}>Capture photo</button></div>
    </div> : <>
      <div className={`photo-preview ${preview ? "has-photo" : ""}`}>
        {preview ? <img src={preview} alt="Menu item photo preview" /> : <span>Add a photo of this item</span>}
      </div>
      <div className="photo-actions">
        <button type="button" className="secondary-button" disabled={disabled || preparing} onClick={() => void openCamera()}>Take photo</button>
        <button type="button" className="secondary-button" disabled={disabled || preparing} onClick={() => fileInput.current?.click()}>{preview ? "Replace photo" : "Upload photo"}</button>
      </div>
      <input ref={fileInput} className="photo-file-input" type="file" aria-label="Upload menu item photo" accept="image/jpeg,image/png,image/webp" disabled={disabled || preparing} onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; void upload(file); }} />
      {photo && <button type="button" className="photo-reset" disabled={disabled || preparing} onClick={() => onChange(undefined)}>{savedUrl ? "Keep saved photo" : "Remove photo"}</button>}
      {preparing && <p role="status">Preparing photo…</p>}
    </>}
    {error && <p className="error-banner" role="alert">{error}</p>}
  </div>;
}
