import { cameraConstraints } from "./cameraFraming";

function stop(stream: MediaStream) { stream.getTracks().forEach(track => track.stop()); }
async function iphoneId(): Promise<string> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    // Desk View is a different crop; prefer the regular Continuity Camera.
    return devices.find(device => device.kind === "videoinput" && /iphone/i.test(device.label)
      && !/desk\s*view/i.test(device.label))?.deviceId ?? "";
  } catch { return ""; }
}

export async function preferredCamera(id: string, current: () => boolean): Promise<MediaStream | null> {
  async function open(deviceId: string) {
    if (!current()) return null;
    const stream = await navigator.mediaDevices.getUserMedia(cameraConstraints(deviceId));
    if (!current()) { stop(stream); return null; }
    return stream;
  }
  async function prefer(phone: string) {
    try { return await open(phone); }
    catch (error) {
      if (!(error instanceof DOMException) || !["NotFoundError", "NotReadableError", "OverconstrainedError", "AbortError"].includes(error.name)) throw error;
      return open("");
    }
  }
  // An explicit dropdown choice wins over the default preference.
  if (id) return open(id);
  const knownPhone = await iphoneId();
  if (knownPhone) return prefer(knownPhone);
  const initial = await open("");
  if (!initial) return null;
  // Browsers may hide camera labels until permission has been granted.
  const phone = await iphoneId();
  if (!current()) { stop(initial); return null; }
  if (!phone || initial.getVideoTracks()[0]?.getSettings().deviceId === phone) return initial;
  stop(initial);
  return prefer(phone);
}
