import type { MenuPhoto } from "../../api/client";

export function cameraConstraints(deviceId = ""): MediaStreamConstraints {
  return { audio: false, video: {
    ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: "environment" } }),
    width: { ideal: 1280 }, height: { ideal: 960 },
  } };
}

// Both previews use object-fit: cover in the same square viewport.
export function cropCamera(video: HTMLVideoElement, width = 1024): HTMLCanvasElement {
  if (!video.videoWidth || !video.videoHeight) throw new Error("Wait for the camera image.");
  const side = Math.min(video.videoWidth, video.videoHeight);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = Math.min(width, side);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser cannot capture the camera.");
  context.drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2, side, side, 0, 0, canvas.width, canvas.height);
  return canvas;
}

export function cameraPhoto(video: HTMLVideoElement): MenuPhoto {
  const photo = { data_base64: cropCamera(video).toDataURL("image/jpeg", 0.8).split(",")[1] };
  if (!photo.data_base64 || photo.data_base64.length > 1_800_000) throw new Error("Camera image is too large.");
  return photo;
}
