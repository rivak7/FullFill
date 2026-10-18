// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { orderNumber } from "../src/orderNumber";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { JSDOM } from "jsdom";
import { ApiError, orderApi } from "../src/api/client";
import type { OrderState } from "../src/api/generated/contracts";
import { CameraCheckPanel } from "../src/features/orders/CameraCheckPanel";
import { SceneGuard, SceneTrigger, isEmptyMat } from "../src/features/orders/sceneTrigger";
import { changeSetting } from "../src/settings";
import { amberReason, toScreenState } from "../src/features/station/screenState";
import { readCheckActivity, recordCheckAttempt } from "../src/features/orders/CheckActivity";
import { readCvLogs } from "../src/features/orders/CvLogs";

vi.mock("../src/api/client", async importOriginal => ({ ...await importOriginal<typeof import("../src/api/client")>(), orderApi: { cameraConfig: vi.fn(), checkCamera: vi.fn(), confirmCamera: vi.fn() } }));

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
  vi.stubGlobal("localStorage", new JSDOM("", { url: "http://localhost/" }).window.localStorage);
  vi.stubGlobal("sessionStorage", new JSDOM("", { url: "http://localhost/" }).window.sessionStorage);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(640);
  vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(480);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(4096) }) } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,cGhvdG8=");
  stopTrack = vi.fn();
  const track = { stop: stopTrack, addEventListener: vi.fn(), getSettings: () => ({ deviceId: "camera" }) };
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ active: true, getTracks: () => [track], getVideoTracks: () => [track] }), enumerateDevices: vi.fn().mockResolvedValue([]) } });
  vi.mocked(orderApi.cameraConfig).mockResolvedValue({ configured: true });
  vi.mocked(orderApi.checkCamera).mockResolvedValue(checked());
  onResult = vi.fn(); onBusyChange = vi.fn();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals();
});
let shown: { order: OrderState | null; disabled: boolean; pauseToken: number } = { order: null, disabled: false, pauseToken: 0 };
let checkToken = 0;
async function render(order: OrderState | null = ticket(), disabled = false, pauseToken = 0) {
  shown = { order, disabled, pauseToken };
  await act(async () => root.render(<CameraCheckPanel workerId="worker" order={order ?? undefined} disabled={disabled} pauseToken={pauseToken} checkToken={checkToken} onResult={onResult} onBusyChange={onBusyChange} />));
}
// The kitchen's "Check now" button lives in the override row and bumps checkToken.
async function checkNow() {
  checkToken++;
  await render(shown.order, shown.disabled, shown.pauseToken);
}
const automatic = () => container.querySelector("[data-auto]")?.getAttribute("data-auto") === "on";
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find(button => button.textContent === label);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
async function camera() {
  await click("Enable camera");
  await act(async () => container.querySelector("video")!.dispatchEvent(new Event("loadeddata")));
}

it("takes one look when automatic checks start, then leaves a red or green view alone", async () => {
  await render(); await camera();
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(automatic()).toBe(true);
  await click("Turn off camera");
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("rechecks an amber result once, five seconds after a slow check finishes", async () => {
  const unsure = checked(); unsure.current_check!.verdict = "unsure";
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.checkCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  vi.mocked(orderApi.checkCamera).mockResolvedValue(unsure);
  await render(); await camera();
  await observe(0, 20000);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await act(async () => resolve(unsure));
  await observe(0, 4750);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await observe(0, 250);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(readCvLogs()[0].trigger).toBe("recheck after amber");
  await observe(0, 60000);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
});

it("does not periodically check fulfilled orders, unclaimed orders, or an empty queue", async () => {
  const fulfilled = ticket(); fulfilled.disposition = "verified";
  fulfilled.current_check = { ...checked().current_check!, verdict: "pass" };
  await render(fulfilled); await camera(); await observe(0, 10000);
  await render(ticket(), true); await observe(0, 10000);
  await render(null); await observe(0, 10000);
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
});

it("asks for boxes and model input only when they are turned on in settings", async () => {
  vi.mocked(orderApi.checkCamera).mockResolvedValue({ ...checked(), diagnostics: { provider_called: true, image: null, targets: [], references: [], observations: null, timings_ms: { square_order: 400, perceptron: 2100 } } });
  changeSetting("boxes", true);
  await render(); await camera(); await checkNow();
  expect(vi.mocked(orderApi.checkCamera).mock.calls[0][0]).toMatchObject({ boxes: true, photos: false });
  expect(readCvLogs()[0].events.map(event => event.message).join(" ")).toContain("Server steps: square order 0.4 s, perceptron 2.1 s, network 0.0 s.");
});

it("binds one snapshot to the captured ticket and never relabels a late result", async () => {
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.checkCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await render(); await camera(); await checkNow();
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[0][0]).toEqual({ worker_id: "worker", order_id: "first", expected_revision: 3, photo: { data_base64: "cGhvdG8=" }, boxes: false, photos: false, confirmed: true });
  await render(ticket("second"), true);
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const withdrawn = checked(); withdrawn.current_check!.execution_status = "superseded"; withdrawn.current_check!.verdict = null;
  vi.mocked(orderApi.confirmCamera).mockResolvedValue(withdrawn);
  await act(async () => resolve(checked()));
  // The ticket changed mid-check, so the completed result is withdrawn.
  expect(orderApi.confirmCamera).toHaveBeenCalledWith(expect.objectContaining({ order_id: "first", scene_unchanged: false }));
  expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ order: expect.objectContaining({ order_id: "first" }) }), false);
  expect(onBusyChange.mock.calls.map(call => call[0])).toEqual([true, false]);
});

it("captures the whole frame at the same JPEG resolution as menu photos", async () => {
  vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1920);
  vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1080);
  const drawImage = vi.fn();
  vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage, getImageData: () => ({ data: new Uint8ClampedArray(4096) }) } as unknown as CanvasRenderingContext2D);
  await render(); await camera(); await checkNow();
  expect(drawImage).toHaveBeenCalledWith(container.querySelector("video"), 0, 0, 1920, 1080, 0, 0, 1024, 576);
  expect(HTMLCanvasElement.prototype.toDataURL).toHaveBeenCalledWith("image/jpeg", 0.8);
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } } });
});

it("retries a failed check once with a new photo, then stops auto checking", async () => {
  vi.mocked(orderApi.checkCamera).mockRejectedValue(new ApiError("Camera check failed during vision provider.", 502, { provider_called: true, image: null, targets: [], references: [], observations: null, raw_answer: "{\"items\": []}" }));
  await render(); await camera();
  await checkNow();
  expect(automatic()).toBe(true);
  expect(readCvLogs()[0].events.map(event => event.message).join(" ")).toContain('Perceptron answered: {"items": []}');
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(readCvLogs()[0].trigger).toBe("retry after error");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("vision provider");
  expect(automatic()).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(readCvLogs()[0].result).toBe("Request failed");
});

it("does not retry a request the server rejected", async () => {
  vi.mocked(orderApi.checkCamera).mockRejectedValueOnce(new ApiError("This order changed. Refresh before checking it.", 409));
  await render(); await camera();
  await checkNow();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("This order changed");
  expect(automatic()).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
});

it("records and copies a diagnostic timeline without saving camera images", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  await render(); await camera(); await checkNow();
  const log = readCvLogs()[0];
  expect(log.orderId).toBe("first");
  expect(log.trigger).toBe("manual");
  expect(log.result).toBe("Unfulfilled");
  expect(log.finishedAt).toBeDefined();
  expect(log.events.map(event => event.message).join(" ")).toContain("Expected: 1× Fries");
  await click("Copy logs");
  const exported = writeText.mock.calls[0][0];
  expect(exported).toContain(log.id);
  expect(exported).not.toContain("data_base64");
  expect(exported).not.toContain("cGhvdG8=");
  await act(async () => root.unmount());
  root = createRoot(container); await render();
  expect(readCvLogs()[0].id).toBe(log.id);
  await click("Clear logs");
  expect(readCvLogs()).toHaveLength(0);
  expect(readCheckActivity()).toHaveLength(1);
});

it("allows checks beyond the old caps without a forced wait and records attempts", async () => {
  await render(); await camera();
  for (let i = 0; i < 25; i++) await checkNow();
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(25);
  expect(readCheckActivity()).toHaveLength(25);
  expect(container.textContent).not.toContain("Session limit reached");
});

it("keeps usage across remounts, includes failed attempts, and expires time windows", async () => {
  await render(); await camera(); await checkNow();
  await act(async () => vi.advanceTimersByTimeAsync(10 * 60000));
  vi.mocked(orderApi.checkCamera).mockRejectedValueOnce(new Error("Unavailable"));
  await checkNow();
  await act(async () => root.unmount());
  root = createRoot(container); await render();
  const details = container.querySelector<HTMLDetailsElement>(".check-activity")!;
  expect(details.open).toBe(false);
  await act(async () => { details.open = true; details.dispatchEvent(new Event("toggle")); });
  expect(container.querySelector("output")?.textContent).toBe("2 check attempts");
  const period = container.querySelector<HTMLSelectElement>('[aria-label="Check activity period"]')!;
  await act(async () => { period.value = "5"; period.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(container.querySelector("output")?.textContent).toBe("1 check attempt");
  await act(async () => { localStorage.setItem("fullfill.check-attempt.v1.other-tab", String(Date.now())); window.dispatchEvent(new Event("storage")); });
  expect(container.querySelector("output")?.textContent).toBe("2 check attempts");
  await act(async () => vi.advanceTimersByTimeAsync(5 * 60000));
  expect(container.querySelector("output")?.textContent).toBe("0 check attempts");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
});

it("retains only recent timestamps and deduplicates an attempt ID", () => {
  recordCheckAttempt("same"); recordCheckAttempt("same");
  localStorage.setItem("fullfill.check-attempt.v1.invalid", "bad");
  localStorage.setItem("fullfill.check-attempt.v1.expired", String(Date.now() - 86400000));
  localStorage.setItem("fullfill.check-attempt.v1.future", String(Date.now() + 100));
  expect(readCheckActivity()).toHaveLength(1);
  expect(localStorage.length).toBe(2);
  expect(readCheckActivity(Date.now() + 100)).toHaveLength(2);
});

it("keeps automatic mode enabled across tab switches and waits for visible settling", async () => {
  await render(); await camera();
  await observe(0);
  await observe(80, 500);
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await observe(80, 10000);
  expect(automatic()).toBe(true);
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await observe(80, 375);
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  await observe(80, 250);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
});

it("disables paid checks when the backend is not configured while allowing preview", async () => {
  vi.mocked(orderApi.cameraConfig).mockResolvedValue({ configured: false });
  await render(); await camera(); await checkNow();
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  expect(container.textContent).toContain("AI checks unavailable");
});

function sampled(scene: SceneTrigger, frame: Uint8Array, from: number, to: number) {
  let triggered = false;
  for (let time = from; time <= to; time += 250) triggered = scene.sample(frame, time) || triggered;
  return triggered;
}

it("requires movement and settling, ignores hand waves, and suppresses unchanged scenes", () => {
  const scene = new SceneTrigger();
  const frame = (value: number) => new Uint8Array(1024).fill(value);
  expect(sampled(scene, frame(0), 0, 3000)).toBe(false);
  expect(sampled(scene, frame(80), 3250, 3500)).toBe(false);
  expect(scene.sample(frame(80), 3750)).toBe(true);
  scene.submitted(frame(80));
  expect(sampled(scene, frame(80), 5000, 9000)).toBe(false);
  scene.sample(frame(200), 9250);
  expect(sampled(scene, frame(80), 9500, 11500)).toBe(false);
  const untouched = new SceneTrigger();
  untouched.sample(frame(0), 0); untouched.sample(frame(200), 250);
  expect(sampled(untouched, frame(0), 500, 2500)).toBe(false);
});

it("waits for a stable intermediate scene before checking an identical next meal", () => {
  const scene = new SceneTrigger();
  const meal = new Uint8Array(1024).fill(80), empty = new Uint8Array(1024);
  scene.submitted(meal); scene.nextOrder();
  expect(sampled(scene, meal, 0, 3000)).toBe(false);
  expect(scene.handoff).toBe("remove");
  // A brief hand wave returning to the previous meal isn't a handoff.
  scene.sample(empty, 3250);
  expect(sampled(scene, meal, 3500, 5500)).toBe(false);
  expect(scene.handoff).toBe("remove");
  expect(sampled(scene, empty, 5750, 9000)).toBe(false);
  expect(scene.handoff).toBe("place");
  expect(sampled(scene, meal, 9250, 9500)).toBe(false);
  expect(scene.sample(meal, 9750)).toBe(true);
});

it("does not treat time away from the camera as handoff evidence", () => {
  const scene = new SceneTrigger();
  const meal = new Uint8Array(1024).fill(80), empty = new Uint8Array(1024);
  scene.submitted(meal); scene.nextOrder();
  sampled(scene, empty, 0, 1000);
  expect(scene.handoff).toBe("place");
  expect(sampled(scene, meal, 5000, 8000)).toBe(false);
  expect(scene.handoff).toBe("remove");
});

it("preserves a clear-and-replace sequence through queue and claim updates", () => {
  const scene = new SceneTrigger();
  const meal = new Uint8Array(1024).fill(80), empty = new Uint8Array(1024);
  scene.submitted(meal); scene.nextOrder();
  sampled(scene, empty, 0, 1000);
  scene.nextOrder();
  expect(scene.handoff).toBe("place");
  expect(sampled(scene, meal, 1250, 2750)).toBe(true);
});

it("ends a passed order only once the mat is back to the empty mat seen at camera start", () => {
  const scene = new SceneTrigger();
  const bare = new Uint8Array(1024).fill(200), meal = bare.slice(), half = bare.slice();
  for (let i = 0; i < 300; i++) meal[i] = 60;
  for (let i = 0; i < 100; i++) half[i] = 60;
  scene.learnEmptyMat();
  sampled(scene, bare, 0, 1000);
  scene.submitted(meal); scene.nextOrder();
  // Half the bag packed, then a pause: still waiting for the mat to clear.
  sampled(scene, half, 1250, 4000);
  expect(scene.handoff).toBe("remove");
  // A brighter room still reads as the empty mat.
  sampled(scene, bare.map(value => value + 20), 4250, 6000);
  expect(scene.handoff).toBe("place");
});

it("falls back to any settled change when the camera started with an order on the mat", () => {
  const scene = new SceneTrigger();
  const bare = new Uint8Array(1024).fill(200), meal = bare.slice(), half = bare.slice();
  for (let i = 0; i < 300; i++) meal[i] = 60;
  for (let i = 0; i < 100; i++) half[i] = 60;
  scene.learnEmptyMat();
  sampled(scene, meal, 0, 1000);
  scene.submitted(meal); scene.nextOrder();
  sampled(scene, half, 1250, 4000);
  expect(scene.handoff).toBe("place");
});

it("goes straight to the next order when the ticket changes on an empty mat", () => {
  const scene = new SceneTrigger();
  const bare = new Uint8Array(1024).fill(200);
  scene.learnEmptyMat();
  sampled(scene, bare, 0, 1000);
  scene.nextOrder();
  expect(scene.handoff).toBe("place");
});

it("detects a small added packet while ignoring an isolated noisy pixel", () => {
  const scene = new SceneTrigger();
  const baseline = new Uint8Array(1024).fill(80);
  scene.sample(baseline, 0);
  const noise = baseline.slice(); noise[0] = 200;
  expect(sampled(scene, noise, 250, 2000)).toBe(false);
  const packet = baseline.slice();
  for (let row = 0; row < 4; row++) for (let col = 0; col < 8; col++) packet[row * 32 + col] = 200;
  expect(sampled(scene, packet, 2250, 2500)).toBe(false);
  expect(scene.sample(packet, 2750)).toBe(true);
});

// Two sauce packets cover only a few pixels of the 32-px preview and barely move
// the averages, so clearing them used to leave "Bag it and clear the mat" up.
function withPackets(bare: Uint8Array, value = 150) {
  const frame = bare.slice();
  for (const [row, col] of [[10, 10], [10, 11], [11, 10], [20, 22], [21, 22]]) frame[row * 32 + col] = value;
  return frame;
}

it("sees the mat cleared when only two small packets are taken off", () => {
  const scene = new SceneTrigger();
  const bare = new Uint8Array(1024).fill(210);
  scene.learnEmptyMat();
  sampled(scene, bare, 0, 1000);
  const packets = withPackets(bare);
  scene.submitted(packets); scene.nextOrder();
  sampled(scene, packets, 1250, 3000);
  expect(scene.handoff).toBe("remove");
  sampled(scene, bare, 3250, 4500);
  expect(scene.handoff).toBe("place");
  // And two packets placed on the bare mat start a check.
  expect(sampled(scene, packets, 4750, 6000)).toBe(true);
});

it("sees a mustard packet on cardboard even though both are equally bright", () => {
  const cardboard = new Uint8Array(32 * 32 * 3);
  for (let p = 0; p < 1024; p++) cardboard.set([190, 150, 110], p * 3); // grey ≈ 150
  const packet = cardboard.slice();
  for (const p of [330, 331, 362]) packet.set([230, 185, 35], p * 3); // mustard, grey ≈ 150
  expect(isEmptyMat(cardboard, cardboard)).toBe(true);
  expect(isEmptyMat(packet, cardboard)).toBe(false);
});

it("moves on after a swapped mat stays still, and learns the new mat", () => {
  const scene = new SceneTrigger();
  // Different mats also leave different strips of carpet in view.
  const mat = (value: number, carpet: number) => Uint8Array.from({ length: 1024 }, (_, i) => i % 32 < carpet ? 60 : value);
  const paper = mat(230, 6), cardboard = mat(160, 16);
  scene.learnEmptyMat();
  sampled(scene, paper, 0, 1000);
  const packets = withPackets(cardboard, 250);
  scene.submitted(packets); scene.nextOrder();
  // Bare cardboard never matches the paper the camera learned at start...
  sampled(scene, cardboard, 1250, 4000);
  expect(scene.handoff).toBe("remove");
  // ...but once it has stayed still long enough the order counts as cleared.
  sampled(scene, cardboard, 4250, 6000);
  expect(scene.handoff).toBe("place");
  // The next order on the cardboard ends as soon as the cardboard is bare again.
  scene.submitted(packets); scene.nextOrder();
  sampled(scene, cardboard, 6250, 7250);
  expect(scene.handoff).toBe("place");
});

// Once an order passes, every sample looks at the spots where it sat; no settle or
// movement event is needed beyond a quarter second of stillness.
function passedOrder() {
  const scene = new SceneTrigger();
  const bare = new Uint8Array(1024).fill(210), meal = bare.slice();
  for (let row = 8; row < 20; row++) for (let col = 8; col < 20; col++) meal[row * 32 + col] = 70;
  scene.learnEmptyMat();
  sampled(scene, bare, 0, 1000);
  scene.submitted(meal); scene.nextOrder();
  scene.sample(meal, 1125);
  return { scene, bare, meal };
}

it("moves on within a quarter second of the order spots showing the bare mat", () => {
  const { scene, bare } = passedOrder();
  for (const time of [1250, 1375]) scene.sample(bare, time);
  expect(scene.handoff).toBe("remove");
  scene.sample(bare, 1500);
  expect(scene.handoff).toBe("place");
  expect(scene.lastClearCheck).toMatchObject({ left: 0, spots: 144, cleared: "empty mat" });
});

it("ignores the paper shifting or a cable elsewhere in view when the order is gone", () => {
  const { scene, bare } = passedOrder();
  const moved = bare.slice();
  for (let row = 0; row < 32; row++) for (let col = 26; col < 32; col++) moved[row * 32 + col] = 40;
  for (const time of [1250, 1375, 1500]) scene.sample(moved, time);
  expect(scene.handoff).toBe("place");
  // That view is not an order, so it doesn't start a check for the next ticket.
  expect(sampled(scene, moved, 1750, 3000)).toBe(false);
});

it("keeps waiting while a packet is left where the order sat, or a hand is still moving", () => {
  const { scene, bare } = passedOrder();
  const packet = bare.slice(); packet[10 * 32 + 10] = 120; packet[10 * 32 + 11] = 120; packet[11 * 32 + 10] = 120;
  for (let time = 1250; time <= 3500; time += 125) scene.sample(packet, time);
  expect(scene.handoff).toBe("remove");
  expect(scene.lastClearCheck?.left).toBe(3);
  // The packet is taken away by a hand that keeps moving outside the order spots.
  const hand = (offset: number) => { const frame = bare.slice(); for (let i = 0; i < 160; i++) frame[offset + i] = 90; return frame; };
  for (let time = 3625, step = 0; time <= 4500; time += 125, step++) scene.sample(hand(step % 2 ? 640 : 800), time);
  expect(scene.handoff).toBe("remove");
  for (const time of [4625, 4750, 4875]) scene.sample(bare, time);
  expect(scene.handoff).toBe("place");
});

it("learns the mat as it is now after the slow clear, so the next order clears quickly", () => {
  const { scene, bare } = passedOrder();
  // The paper turned under the order: its edge now crosses the spots where the order sat.
  const turned = bare.slice();
  for (let row = 8; row < 20; row++) for (let col = 8; col < 11; col++) turned[row * 32 + col] = 40;
  sampled(scene, turned, 1250, 4000);
  expect(scene.handoff).toBe("remove");
  sampled(scene, turned, 4250, 5500);
  expect(scene.handoff).toBe("place");
  expect(scene.lastClearCheck?.cleared).toBe("still for 4 s");
  const meal = turned.slice();
  for (let row = 12; row < 24; row++) for (let col = 14; col < 26; col++) meal[row * 32 + col] = 70;
  scene.submitted(meal); scene.nextOrder();
  scene.sample(meal, 5625);
  for (const time of [5750, 5875, 6000]) scene.sample(turned, time);
  expect(scene.handoff).toBe("place");
});

it("still sees the bare mat after the phone shifts by a pixel", () => {
  const bare = new Uint8Array(1024).fill(210);
  for (let row = 0; row < 32; row++) for (let col = 0; col < 6; col++) bare[row * 32 + col] = 60; // carpet edge
  const shifted = bare.map((_, i) => bare[Math.floor(i / 32) * 32 + Math.max(0, (i % 32) - 1)]);
  expect(isEmptyMat(shifted, bare)).toBe(true);
  expect(isEmptyMat(withPackets(shifted), bare)).toBe(false);
});

it("shows an unexpected unidentified item as orange, matching the comparison verdict", () => {
  const state = checked();
  state.disposition = "needs_review";
  state.current_check!.verdict = "unsure";
  state.current_check!.discrepancies = [{ kind: "unexpected", message: "Not on the ticket: Drink", line_ids: [] }];
  expect(toScreenState(state).tone).toBe("amber");
});

it("keeps the exact submitted photo labeled with its ticket after selection changes", async () => {
  await render(); await camera(); await checkNow();
  await render(ticket("second"));
  expect(container.querySelector(".camera-last-photo summary")?.textContent).toContain(orderNumber("first"));
  expect(container.querySelector(".camera-last-photo img")?.getAttribute("src")).toBe("data:image/jpeg;base64,cGhvdG8=");
});

it("rechecks uncertain results but respects manual corrections", async () => {
  const state = checked(); state.current_check!.verdict = "unsure";
  vi.mocked(orderApi.checkCamera).mockResolvedValueOnce(state);
  await render(); await camera();
  expect(automatic()).toBe(true);
  await checkNow();
  expect(automatic()).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  // A manual override stands: auto-check stays on but waits for the mat to change.
  await render(ticket(), false, 1);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(automatic()).toBe(true);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
});

it("failed, malformed, and outdated results cannot display green", () => {
  for (const kind of ["failed", "missing-verdict", "stale", "wrong-order"] as const) {
    const state = checked();
    state.current_check!.verdict = "pass";
    if (kind === "failed") state.current_check!.execution_status = "failed";
    if (kind === "missing-verdict") state.current_check!.verdict = null;
    if (kind === "stale") state.current_check!.order_revision = 2;
    if (kind === "wrong-order") state.current_check!.order_id = "different";
    expect(toScreenState(state).tone).toBe("amber");
  }
});

it("keeps uncertain items visible alongside definite shortages", () => {
  const state = checked();
  state.current_check!.discrepancies = [
    { kind: "missing", line_ids: ["line"], message: "Missing: 1 Fries", expected_quantity: 2, observed_quantity: 1 },
    { kind: "unsure", line_ids: [], message: "Read the drink label." },
  ];
  const screen = toScreenState(state);
  expect(screen.tone).toBe("red");
  expect(screen.problems).toHaveLength(2);
});

it("keeps the first reason a result was invalidated", () => {
  const guard = new SceneGuard();
  expect(guard.unchanged()).toBe(true);
  guard.invalidate("ticket_changed"); guard.invalidate("tab_hidden");
  expect(guard.unchanged()).toBe(false);
  expect(guard.reason).toBe("ticket_changed");
});

it.each(["still", "motion", "hidden", "closed"])("confirms the captured scene safely: %s", async kind => {
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.checkCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  vi.mocked(orderApi.confirmCamera).mockImplementation(async body => {
    const state = checked();
    state.current_check!.execution_status = body.scene_unchanged ? "completed" : "superseded";
    state.current_check!.verdict = body.scene_unchanged ? "pass" : null;
    state.disposition = body.scene_unchanged ? "verified" : "needs_review";
    return state;
  });
  await render(); await camera(); await checkNow();
  await act(async () => vi.advanceTimersByTimeAsync(1500));
  if (kind === "motion") {
    vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(4096).fill(200) }) } as unknown as CanvasRenderingContext2D);
    await act(async () => vi.advanceTimersByTimeAsync(250));
  } else if (kind === "hidden") {
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  } else if (kind === "closed") await click("Turn off camera");
  const pending = checked(); pending.current_check!.execution_status = "awaiting_confirmation"; pending.current_check!.verdict = null;
  await act(async () => resolve(pending));
  // Movement after the photo (bagging, a hand) never revokes the result.
  const kept = kind === "still" || kind === "motion";
  expect(orderApi.confirmCamera).toHaveBeenCalledWith(expect.objectContaining({ scene_unchanged: kept }));
  expect(toScreenState(onResult.mock.calls[0][0]).tone).toBe(kept ? "green" : "amber");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const events = readCvLogs()[0].events.map(event => event.message).join(" ");
  if (kind === "motion") expect(events).not.toContain("invalidated");
  if (kind === "hidden") expect(events).toContain("tab_hidden");
  if (kind === "closed") expect(events).toContain("camera_stopped");
  if (kind === "hidden") {
    expect(automatic()).toBe(true);
    await observe(0, 10000);
    expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    await observe(0, 1000);
    expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
    await observe(0, 4000);
    expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  }
});

it("never revokes a green result after it is confirmed", async () => {
  const pending = checked(); pending.current_check!.execution_status = "awaiting_confirmation";
  vi.mocked(orderApi.checkCamera).mockResolvedValue(pending);
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.confirmCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await render(); await camera(); await checkNow();
  await click("Turn off camera");
  const accepted = checked(); accepted.current_check!.verdict = "pass";
  await act(async () => resolve(accepted));
  expect(vi.mocked(orderApi.confirmCamera).mock.calls.map(call => call[0].scene_unchanged)).toEqual([true]);
  expect(toScreenState(onResult.mock.calls[0][0]).tone).toBe("green");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
});

function showFrame(value: number) {
  vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(4096).fill(value) }) } as unknown as CanvasRenderingContext2D);
}
async function observe(value: number, milliseconds = 2000) {
  showFrame(value);
  await act(async () => vi.advanceTimersByTimeAsync(milliseconds));
}

it("automatically checks consecutive identical meals without a handoff button or empty-scene calls", async () => {
  await render(); await camera();
  expect(container.textContent).not.toContain("New order placed");
  expect(automatic()).toBe(true);
  await observe(0); // First baseline is local only.
  await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await render(ticket("second"));
  await observe(80, 10000); // Untouched food cannot check the next ticket.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("Bag it and clear the mat");
  await observe(200, 250); await observe(80); // Brief hand wave.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await observe(0, 3000); // Cleared view is observed without an AI call.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("Place the next order");
  await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[1][0].order_id).toBe("second");
  await observe(80, 10000); // A red result on an untouched meal stands.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
});

it("keeps handoff evidence while waiting for the new ticket claim", async () => {
  await render(); await camera(); await observe(0); await observe(80);
  await render(ticket("second"), true);
  await observe(0); await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await render({ ...ticket("second"), order: { ...ticket("second").order, revision: 4 } });
  await observe(80, 250);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[1][0].expected_revision).toBe(4);
});

it("keeps auto-check always on and checks right away on Check now", async () => {
  await render(); await camera(); await checkNow();
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(container.querySelector('input[type="checkbox"]')).toBeNull();
  await render(ticket("second"));
  await checkNow();
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[1][0].order_id).toBe("second");
  expect(automatic()).toBe(true);
});

it("asks for the camera when Check now is pressed with it off", async () => {
  await render(); await checkNow();
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Turn on the camera");
});

it("invalidates a snapshot when the ticket contents change without turning automatic mode off", async () => {
  await render(); await camera(); await observe(0); await observe(80);
  await render({ ...ticket(), order: { ...ticket().order, revision: 4 } });
  await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const changed = ticket(); changed.order.lines[0].quantity = 2;
  await render(changed); await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(automatic()).toBe(true);
  expect(container.textContent).not.toContain("New order placed");
});

it("shows unidentified items in amber and confidently wrong items in red", () => {
  const state = checked(); state.disposition = "needs_review";
  state.current_check!.verdict = "unsure";
  state.current_check!.discrepancies = [{ kind: "unidentified", message: "Unidentified item: Container", line_ids: [] }];
  expect(toScreenState(state).tone).toBe("amber");
  state.current_check!.verdict = "fail";
  state.current_check!.discrepancies.push({ kind: "wrong_item", message: "Wrong item: Chips", line_ids: [] });
  expect(toScreenState(state).tone).toBe("red");
});

it("always says why an amber screen is unsure", () => {
  const state = checked(); state.current_check!.verdict = "unsure";
  state.current_check!.discrepancies = [
    { kind: "unsure", message: "Check Ketchup packet: cannot count the items reliably", line_ids: ["line"] },
    { kind: "unidentified", message: "Unidentified item: Container", line_ids: [] },
  ];
  const screen = toScreenState(state);
  expect(screen.detail).toBeNull();
  expect(screen.problems).toHaveLength(2);
  expect(amberReason(screen)).toBe("Check Ketchup packet: cannot count the items reliably (+1 more)");
  state.current_check!.discrepancies = [];
  expect(amberReason(toScreenState(state))).toBe("No reliable result. Check manually or take a new photo.");
  const marked = ticket(); marked.disposition = "needs_review";
  expect(amberReason(toScreenState(marked))).toBe("Marked for review by staff.");
  state.current_check!.verdict = "pass";
  expect(amberReason(toScreenState(state))).toBeNull();
});


it("automatically checks the first ticket arriving after the camera starts with an empty queue", async () => {
  await render(null); await camera();
  await observe(0);
  await render(ticket()); await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
});

it("shows exact input photos and model reports in a separate tab without stopping the camera", async () => {
  const diagnostic = {
    provider_called: true, image: "data:image/jpeg;base64,bW9kZWw=",
    references: [{ item_id: "fries", name: "Fries", revision: 7, role: "expected" as const, image: "data:image/jpeg;base64,cmVm" }],
    targets: [{ target_id: "fries", line_ids: ["line"], item_id: "fries", name: "Fries", expected_quantity: 1 }],
    observations: { schema_version: 1 as const, capture_id: "capture", targets: [{ target_id: "fries", status: "unsure" as const, observed_quantity: null, reason: "Covered" }], unexpected_items: [{ name: "Drink", quantity: 1 }], scene_uncertainty: "Hands in frame", provider: { provider: "perceptron", model: "test-model", prompt_version: "test", latency_ms: 2300, prompt_tokens: 1800, completion_tokens: 0 } },
  };
  vi.mocked(orderApi.checkCamera).mockResolvedValue({ ...checked(), diagnostics: diagnostic });
  await render(); await camera(); await click("CV logs");
  // The live camera stays on screen as a thumbnail so it keeps watching the mat.
  expect(container.querySelector('#camera-panel')!.hasAttribute("hidden")).toBe(false);
  expect(container.querySelector('#camera-panel')!.classList.contains("camera-panel-mini")).toBe(true);
  expect(container.querySelector('#logs-panel')!.hasAttribute("hidden")).toBe(false);
  expect(stopTrack).not.toHaveBeenCalled();
  await observe(0, 5000);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const logs = container.querySelector('#logs-panel')!;
  expect(logs.querySelector('img[alt="Captured order for this check"]')?.getAttribute("src")).toBe(diagnostic.image);
  expect(logs.querySelector('img[alt="Reference: Fries"]')?.getAttribute("src")).toBe(diagnostic.references[0].image);
  expect(logs.textContent).toContain("Covered");
  expect(logs.textContent).toContain("1 × Drink");
  expect(logs.textContent).toContain("Hands in frame");
  expect(logs.textContent).toContain("Model time2.30 s");
  expect(logs.textContent).toContain("Input tokens1,800");
  expect(logs.textContent).toContain("Output tokens0");
  expect(JSON.stringify(readCvLogs())).not.toContain("data:image");
  expect(readCvLogs()[0].diagnostics?.observations?.targets[0].status).toBe("unsure");
  await click("Clear logs");
  expect(logs.querySelector("img")).toBeNull();
});

it("resumes a camera preview the browser paused, so it still sees the mat clear", async () => {
  await render(); await camera();
  const play = vi.mocked(HTMLMediaElement.prototype.play); play.mockClear();
  const paused = vi.spyOn(HTMLMediaElement.prototype, "paused", "get").mockReturnValue(true);
  await act(async () => vi.advanceTimersByTimeAsync(250));
  expect(play).toHaveBeenCalled();
  paused.mockReturnValue(false); play.mockClear();
  await act(async () => vi.advanceTimersByTimeAsync(250));
  expect(play).not.toHaveBeenCalled();
});

it("advances a passed order as soon as the mat is bare, and logs each clear check", async () => {
  const passed = checked(); passed.current_check!.verdict = "pass"; passed.disposition = "fulfilled";
  vi.mocked(orderApi.checkCamera).mockResolvedValue(passed);
  const onMatCleared = vi.fn();
  const show = (meal: boolean) => vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({
    data: Uint8ClampedArray.from({ length: 4096 }, (_, i) => { const p = i >> 2, row = p >> 5, col = p & 31; return i % 4 === 3 ? 255 : meal && row >= 8 && row < 20 && col >= 8 && col < 20 ? 70 : 210; }),
  }) } as unknown as CanvasRenderingContext2D);
  show(false);
  await act(async () => root.render(<CameraCheckPanel workerId="worker" order={ticket()} pauseToken={0} checkToken={0} onResult={onResult} onBusyChange={onBusyChange} onMatCleared={onMatCleared} />));
  await camera();
  await act(async () => vi.advanceTimersByTimeAsync(1000)); // learns the bare mat
  show(true);
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(onResult.mock.calls[0][1]).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(1500));
  expect(onMatCleared).not.toHaveBeenCalled();
  show(false);
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(onMatCleared).toHaveBeenCalledWith("first");
  const events = readCvLogs()[0].events.map(event => event.message);
  expect(events).toContain("Watching for the mat to clear.");
  expect(events).toContain("Clear check: 144 of 144 order pixels still differ from the bare mat.");
  expect(events).toContain("Mat clear (empty mat): moving to the next order.");
});

it("sees an amber or red order bagged anyway once its spots show the bare mat, without checking the bare mat", () => {
  const scene = new SceneTrigger();
  const bare = new Uint8Array(1024).fill(210), meal = bare.slice(), half = bare.slice();
  for (let row = 8; row < 20; row++) for (let col = 8; col < 20; col++) meal[row * 32 + col] = 70;
  for (let row = 8; row < 14; row++) for (let col = 8; col < 20; col++) half[row * 32 + col] = 70;
  scene.learnEmptyMat();
  sampled(scene, bare, 0, 1000);
  scene.submitted(meal);
  // Taking one item off (fixing an extra) still checks again.
  expect(sampled(scene, half, 1250, 2000)).toBe(true);
  expect(scene.clearedAfterWarning).toBe(false);
  scene.submitted(half);
  scene.sample(bare, 2125);
  expect(scene.clearedAfterWarning).toBe(false);
  expect(scene.sample(bare, 2250)).toBe(false);
  expect(scene.sample(bare, 2375)).toBe(false);
  expect(scene.clearedAfterWarning).toBe(true);
  scene.bagged(bare);
  expect(scene.handoff).toBe("place");
  expect(sampled(scene, bare, 2500, 4000)).toBe(false);
  expect(sampled(scene, meal, 4250, 5000)).toBe(true);
});

it("moves past a red order when the worker bags it anyway, keeping it red", async () => {
  const red = checked(); red.disposition = "unfulfilled";
  vi.mocked(orderApi.checkCamera).mockResolvedValue(red);
  const onBaggedWithWarning = vi.fn();
  const show = (meal: boolean) => vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({
    data: Uint8ClampedArray.from({ length: 4096 }, (_, i) => { const p = i >> 2, row = p >> 5, col = p & 31; return i % 4 === 3 ? 255 : meal && row >= 8 && row < 20 && col >= 8 && col < 20 ? 70 : 210; }),
  }) } as unknown as CanvasRenderingContext2D);
  show(false);
  const render = (order: OrderState) => act(async () => root.render(<CameraCheckPanel workerId="worker" order={order} pauseToken={0} checkToken={0} onResult={onResult} onBusyChange={onBusyChange} onBaggedWithWarning={onBaggedWithWarning} />));
  await render(ticket());
  await camera();
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  show(true);
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await render(onResult.mock.calls[0][0]);
  expect(toScreenState(onResult.mock.calls[0][0]).tone).toBe("red");
  show(false);
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(onBaggedWithWarning).toHaveBeenCalledWith("first");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(readCvLogs()[0].events.map(event => event.message)).toContain("Mat cleared without a pass: warning overridden by bagging, order left unfulfilled. Moving to the next order.");
});
