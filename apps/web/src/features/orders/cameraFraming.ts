import type { MenuPhoto } from "../../api/client";

export function cameraConstraints(deviceId = ""): MediaStreamConstraints {
  return { audio: false, video: {
    ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: "environment" } }),
    width: { ideal: 1280 }, height: { ideal: 960 },
  } };
}

// The whole frame is sent, so items at the sides of a wide mat are not cut off.
// Menu photos and check photos use the same framing.
export function cropCamera(video: HTMLVideoElement, maxSide = 1024): HTMLCanvasElement {
  if (!video.videoWidth || !video.videoHeight) throw new Error("Wait for the camera image.");
  const scale = Math.min(1, maxSide / Math.max(video.videoWidth, video.videoHeight));
  return drawFrame(video, Math.round(video.videoWidth * scale), Math.round(video.videoHeight * scale));
}

// A tiny square copy of the whole frame for motion detection.
export function cameraThumbnail(video: HTMLVideoElement, side: number): HTMLCanvasElement {
  if (!video.videoWidth || !video.videoHeight) throw new Error("Wait for the camera image.");
  return drawFrame(video, side, side);
}

function drawFrame(video: HTMLVideoElement, width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = width; canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser cannot capture the camera.");
  context.drawImage(video, 0, 0, video.videoWidth, video.videoHeight, 0, 0, width, height);
  return canvas;
}

export function cameraPhoto(video: HTMLVideoElement): MenuPhoto {
  const photo = { data_base64: cropCamera(video).toDataURL("image/jpeg", 0.8).split(",")[1] };
  if (!photo.data_base64 || photo.data_base64.length > 1_800_000) throw new Error("Camera image is too large.");
  return photo;
}
