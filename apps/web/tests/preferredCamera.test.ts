// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { preferredCamera } from "../src/features/orders/preferredCamera";

const devices = [
  { kind: "videoinput", deviceId: "mac", label: "FaceTime HD Camera" },
  { kind: "videoinput", deviceId: "desk", label: "iPhone Desk View" },
  { kind: "videoinput", deviceId: "phone", label: "Alex's iPhone Camera" },
];
function stream(deviceId: string) {
  const stop = vi.fn();
  return { stop, value: { getTracks: () => [{ stop }], getVideoTracks: () => [{ getSettings: () => ({ deviceId }) }] } as unknown as MediaStream };
}
function setup() {
  const phone = stream("phone"), mac = stream("mac");
  const getUserMedia = vi.fn().mockResolvedValue(phone.value);
  const enumerateDevices = vi.fn().mockResolvedValue(devices);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia, enumerateDevices } });
  return { phone, mac, getUserMedia, enumerateDevices };
}
afterEach(() => vi.unstubAllGlobals());

it("prefers the regular iPhone over the built-in camera and Desk View", async () => {
  const { phone, getUserMedia } = setup();
  expect(await preferredCamera("", () => true)).toBe(phone.value);
  expect(getUserMedia).toHaveBeenCalledExactlyOnceWith({ audio: false, video: { deviceId: { exact: "phone" }, width: { ideal: 1280 }, height: { ideal: 960 } } });
});

it("discovers iPhone labels after permission, releasing the temporary camera", async () => {
  const { phone, mac, getUserMedia, enumerateDevices } = setup();
  enumerateDevices.mockResolvedValueOnce(devices.map(device => ({ ...device, label: "" })));
  getUserMedia.mockResolvedValueOnce(mac.value);
  expect(await preferredCamera("", () => true)).toBe(phone.value);
  expect(mac.stop).toHaveBeenCalledTimes(1);
  expect(getUserMedia).toHaveBeenCalledTimes(2);
});

it("falls back if the preferred iPhone is unavailable", async () => {
  const { mac, getUserMedia } = setup();
  getUserMedia.mockRejectedValueOnce(new DOMException("Unavailable", "NotReadableError")).mockResolvedValueOnce(mac.value);
  expect(await preferredCamera("", () => true)).toBe(mac.value);
  expect(getUserMedia.mock.calls[1][0].video.facingMode).toEqual({ ideal: "environment" });
});

it("keeps a working default camera when no iPhone is listed", async () => {
  const { mac, getUserMedia, enumerateDevices } = setup();
  enumerateDevices.mockResolvedValue([devices[0]]); getUserMedia.mockResolvedValue(mac.value);
  expect(await preferredCamera("", () => true)).toBe(mac.value);
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  expect(mac.stop).not.toHaveBeenCalled();
});

it("honors manual selections and does not retry denied permission", async () => {
  const { mac, getUserMedia, enumerateDevices } = setup();
  getUserMedia.mockResolvedValueOnce(mac.value);
  expect(await preferredCamera("mac", () => true)).toBe(mac.value);
  expect(enumerateDevices).not.toHaveBeenCalled();
  getUserMedia.mockRejectedValueOnce(new DOMException("Denied", "NotAllowedError"));
  await expect(preferredCamera("", () => true)).rejects.toHaveProperty("name", "NotAllowedError");
  expect(getUserMedia).toHaveBeenCalledTimes(2);
});

it("releases a late stream without opening another camera after cancellation", async () => {
  const { phone, getUserMedia } = setup();
  let current = true;
  getUserMedia.mockImplementation(async () => { current = false; return phone.value; });
  expect(await preferredCamera("", () => current)).toBeNull();
  expect(phone.stop).toHaveBeenCalledTimes(1);
  expect(getUserMedia).toHaveBeenCalledTimes(1);
});
