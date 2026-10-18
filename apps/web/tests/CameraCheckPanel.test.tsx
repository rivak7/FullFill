// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { orderApi } from "../src/api/client";
import type { OrderState } from "../src/api/generated/contracts";
import { CameraCheckPanel } from "../src/features/orders/CameraCheckPanel";
import { SceneTrigger } from "../src/features/orders/sceneTrigger";
import { toScreenState } from "../src/features/station/screenState";

vi.mock("../src/api/client", () => ({ orderApi: { cameraConfig: vi.fn(), checkCamera: vi.fn() } }));

function ticket(id = "first"): OrderState {
  return { order: { schema_version: 1, order_id: id, revision: 3, lines: [{ line_id: "line", item_id: "fries", name: "Fries", quantity: 1, verification_mode: "visible_item" }] }, disposition: "pending", disposition_revision: 3, current_check: null };
}
const checked = (): OrderState => ({ ...ticket(), current_check: { schema_version: 1, check_id: "check", capture_id: "capture", order_id: "first", order_revision: 3, execution_status: "completed", verdict: "fail", disposition: "pending", disposition_revision: 3, discrepancies: [] } });
let container: HTMLDivElement;
let root: Root;
let stopTrack: ReturnType<typeof vi.fn>;
let onResult: ReturnType<typeof vi.fn>;
let onBusyChange: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers(); vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(640);
  vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(480);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(4096) }) } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,cGhvdG8=");
  stopTrack = vi.fn();
  const track = { stop: stopTrack, addEventListener: vi.fn(), getSettings: () => ({ deviceId: "camera" }) };
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track], getVideoTracks: () => [track] }), enumerateDevices: vi.fn().mockResolvedValue([]) } });
  vi.mocked(orderApi.cameraConfig).mockResolvedValue({ configured: true, cooldown_seconds: 10, max_checks_per_order: 20 });
  vi.mocked(orderApi.checkCamera).mockResolvedValue(checked());
  onResult = vi.fn(); onBusyChange = vi.fn();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals();
});
async function render(order = ticket(), disabled = false) {
  await act(async () => root.render(<CameraCheckPanel order={order} disabled={disabled} onResult={onResult} onBusyChange={onBusyChange} />));
}
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find(button => button.textContent === label);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
async function camera() {
  await click("Enable camera");
  await act(async () => container.querySelector("video")!.dispatchEvent(new Event("loadeddata")));
}

it("opening the camera and previewing continuously consumes no AI calls", async () => {
  await render(); await camera();
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  await click("Close camera");
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("binds one snapshot to the captured ticket and never relabels a late result", async () => {
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.checkCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await render(); await camera(); await click("Check order");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[0][0]).toEqual({ order_id: "first", expected_revision: 3, photo: { data_base64: "cGhvdG8=" } });
  await render(ticket("second"), true);
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await act(async () => resolve(checked()));
  expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ order: expect.objectContaining({ order_id: "first" }) }));
  expect(onBusyChange.mock.calls.map(call => call[0])).toEqual([true, false]);
});

it("does not automatically retry failures and stops auto checking on error", async () => {
  vi.mocked(orderApi.checkCamera).mockRejectedValueOnce(new Error("Provider unavailable"));
  await render(); await camera();
  await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await click("Check order");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Provider unavailable");
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
});

it("caps this browser session at ten checks", async () => {
  await render(); await camera();
  for (let i = 0; i < 10; i++) {
    await click("Check order");
    await act(async () => vi.advanceTimersByTimeAsync(10000));
  }
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(10);
  expect(container.textContent).toContain("Session limit reached");
  await click("Check order");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(10);
});

it("pauses automatic checks when the page is hidden", async () => {
  await render(); await camera();
  await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
});

it("disables paid checks when the backend is not configured while allowing preview", async () => {
  vi.mocked(orderApi.cameraConfig).mockResolvedValue({ configured: false, cooldown_seconds: 10, max_checks_per_order: 20 });
  await render(); await camera(); await click("Check order");
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  expect(container.textContent).toContain("AI checks unavailable");
});

it("requires new movement and settling, suppresses unchanged scenes, and respects the cooldown", () => {
  const scene = new SceneTrigger();
  const frame = (value: number) => new Uint8Array(16).fill(value);
  expect(scene.sample(frame(0), 0)).toBe(false);
  expect(scene.sample(frame(0), 3000)).toBe(false);
  expect(scene.sample(frame(80), 3500)).toBe(false);
  expect(scene.sample(frame(80), 4999)).toBe(false);
  expect(scene.sample(frame(80), 5000)).toBe(true);
  scene.submitted(frame(80), 5000);
  expect(scene.sample(frame(80), 20000)).toBe(false);
  // Moving hands out and returning to the same scene cannot resubmit it.
  expect(scene.sample(frame(200), 21000)).toBe(false);
  expect(scene.sample(frame(80), 22000)).toBe(false);
  expect(scene.sample(frame(80), 25000)).toBe(false);
  scene.reset();
  // Selecting the next ticket must not send the previous ticket's food.
  expect(scene.sample(frame(80), 30000)).toBe(false);
  expect(scene.sample(frame(80), 32000)).toBe(false);
  expect(scene.sample(frame(150), 33000)).toBe(false);
  expect(scene.sample(frame(150), 35000)).toBe(true);
  scene.submitted(frame(150), 35000);
  expect(scene.sample(frame(0), 36000)).toBe(false);
  expect(scene.sample(frame(0), 38000)).toBe(false);
  expect(scene.sample(frame(0), 45000)).toBe(true);
});

it("shows an unexpected unidentified item as orange, matching the comparison verdict", () => {
  const state = checked();
  state.disposition = "needs_review";
  state.current_check!.verdict = "unsure";
  state.current_check!.discrepancies = [{ kind: "unexpected", message: "Not on the ticket: Drink", line_ids: [] }];
  expect(toScreenState(state).tone).toBe("amber");
});
