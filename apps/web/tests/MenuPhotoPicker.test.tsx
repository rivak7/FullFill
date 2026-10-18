// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MenuPhotoPicker } from "../src/features/orders/MenuPhotoPicker";

let container: HTMLDivElement;
let root: Root | null;
let getUserMedia: ReturnType<typeof vi.fn>;
let stop: ReturnType<typeof vi.fn>;
let onChange: ReturnType<typeof vi.fn>;
let fakeStream: MediaStream;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div"); document.body.append(container);
  root = createRoot(container);
  stop = vi.fn(); onChange = vi.fn();
  fakeStream = { getTracks: () => [{ stop }], getVideoTracks: () => [{ getSettings: () => ({ deviceId: "built-in" }) }] } as unknown as MediaStream;
  getUserMedia = vi.fn().mockResolvedValue(fakeStream);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([
    { kind: "videoinput", deviceId: "built-in", label: "Built-in camera" },
    { kind: "videoinput", deviceId: "phone", label: "iPhone Camera" },
  ]) } });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

async function render() {
  await act(async () => root!.render(<MenuPhotoPicker savedUrl={null} disabled={false} onChange={onChange} onBusyChange={() => {}} />));
}
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find(button => button.textContent === label);
  expect(button).toBeDefined();
  await act(async () => button!.click());
}

it("captures a photo and releases the camera immediately", async () => {
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ fillRect: vi.fn(), drawImage } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,cGhvdG8=");
  await render(); await click("Take photo");
  expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: false }));
  const video = container.querySelector("video")!;
  Object.defineProperties(video, { videoWidth: { value: 1920 }, videoHeight: { value: 1080 } });
  await act(async () => video.dispatchEvent(new Event("loadeddata")));
  await click("Capture photo");
  expect(drawImage).toHaveBeenCalledWith(video, 420, 0, 1080, 1080, 0, 0, 1024, 1024);
  expect(HTMLCanvasElement.prototype.toDataURL).toHaveBeenCalledWith("image/jpeg", 0.8);
  expect(onChange).toHaveBeenCalledWith({ data_base64: "cGhvdG8=" });
  expect(stop).toHaveBeenCalledTimes(1);
  expect(container.querySelector("video")).toBeNull();
});

it("releases the camera when closed or when leaving the editor", async () => {
  await render(); await click("Take photo"); await click("Close camera");
  expect(stop).toHaveBeenCalledTimes(1);
  await click("Take photo");
  await act(async () => { root!.unmount(); root = null; });
  expect(stop).toHaveBeenCalledTimes(2);
});

it("discards a late permission response after the camera has been closed", async () => {
  let grant!: (stream: MediaStream) => void;
  getUserMedia.mockImplementation(() => new Promise(resolve => { grant = resolve; }));
  await render(); await click("Take photo"); await click("Close camera");
  await act(async () => grant(fakeStream));
  expect(stop).toHaveBeenCalledTimes(1);
  expect(container.querySelector("video")).toBeNull();
  expect(onChange).not.toHaveBeenCalled();
});

it("keeps upload available if camera permission is denied", async () => {
  getUserMedia.mockRejectedValue(new DOMException("Denied", "NotAllowedError"));
  await render(); await click("Take photo");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Camera access was denied");
  expect([...container.querySelectorAll("button")].find(button => button.textContent === "Upload photo")?.disabled).toBe(false);
  expect(onChange).not.toHaveBeenCalled();
});

it("switches to the selected phone camera and releases the previous stream", async () => {
  await render(); await click("Take photo");
  const phoneStop = vi.fn();
  const phone = { getTracks: () => [{ stop: phoneStop }], getVideoTracks: () => [{ getSettings: () => ({ deviceId: "phone" }) }] } as unknown as MediaStream;
  getUserMedia.mockResolvedValueOnce(phone);
  const select = container.querySelector('select')!;
  expect(select.textContent).toContain("iPhone Camera");
  await act(async () => { select.value = "phone"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(stop).toHaveBeenCalledTimes(1);
  expect(getUserMedia).toHaveBeenLastCalledWith({ audio: false, video: { deviceId: { exact: "phone" }, width: { ideal: 1280 }, height: { ideal: 960 } } });
  expect(container.querySelector('video')!.srcObject).toBe(phone);
  await click("Close camera");
  expect(phoneStop).toHaveBeenCalledTimes(1);
});
