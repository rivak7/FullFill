// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { JSDOM } from "jsdom";
import { orderApi } from "../src/api/client";
import type { OrderState } from "../src/api/generated/contracts";
import { CameraCheckPanel } from "../src/features/orders/CameraCheckPanel";
import { SceneGuard, SceneTrigger } from "../src/features/orders/sceneTrigger";
import { toScreenState } from "../src/features/station/screenState";
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
async function render(order: OrderState | null = ticket(), disabled = false, pauseToken = 0) {
  await act(async () => root.render(<CameraCheckPanel workerId="worker" order={order ?? undefined} disabled={disabled} pauseToken={pauseToken} onResult={onResult} onBusyChange={onBusyChange} />));
}
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find(button => button.textContent === label);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
async function camera() {
  await click("Enable camera");
  await act(async () => container.querySelector("video")!.dispatchEvent(new Event("loadeddata")));
}

it("automatically checks an unchanged view every five seconds", async () => {
  await render(); await camera();
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(12);
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
  await click("Close camera");
  expect(stopTrack).toHaveBeenCalledTimes(1);
});

it("waits five seconds after a slow check finishes without overlapping requests", async () => {
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.checkCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await render(); await camera();
  await observe(0, 20000);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await act(async () => resolve(checked()));
  await observe(0, 4750);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await observe(0, 250);
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

it("binds one snapshot to the captured ticket and never relabels a late result", async () => {
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.checkCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await render(); await camera(); await click("Check order");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[0][0]).toEqual({ worker_id: "worker", order_id: "first", expected_revision: 3, photo: { data_base64: "cGhvdG8=" }, diagnostics: true });
  await render(ticket("second"), true);
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await act(async () => resolve(checked()));
  expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ order: expect.objectContaining({ order_id: "first" }) }));
  expect(onBusyChange.mock.calls.map(call => call[0])).toEqual([true, false]);
});

it("captures the same centered square and JPEG resolution as menu photos", async () => {
  vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1920);
  vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1080);
  const drawImage = vi.fn();
  vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage, getImageData: () => ({ data: new Uint8ClampedArray(4096) }) } as unknown as CanvasRenderingContext2D);
  await render(); await camera(); await click("Check order");
  expect(drawImage).toHaveBeenCalledWith(container.querySelector("video"), 420, 0, 1080, 1080, 0, 0, 1024, 1024);
  expect(HTMLCanvasElement.prototype.toDataURL).toHaveBeenCalledWith("image/jpeg", 0.8);
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } } });
});

it("does not automatically retry failures and stops auto checking on error", async () => {
  vi.mocked(orderApi.checkCamera).mockRejectedValueOnce(new Error("Provider unavailable"));
  await render(); await camera();
  await click("Check order");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Provider unavailable");
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(readCvLogs()[0].result).toBe("Request failed");
  expect(readCvLogs()[0].events.at(-1)?.message).toContain("Provider unavailable");
});

it("records and copies a diagnostic timeline without saving camera images", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  await render(); await camera(); await click("Check order");
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
  for (let i = 0; i < 25; i++) await click("Check order");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(25);
  expect(readCheckActivity()).toHaveLength(25);
  expect(container.textContent).not.toContain("Session limit reached");
});

it("keeps usage across remounts, includes failed attempts, and expires time windows", async () => {
  await render(); await camera(); await click("Check order");
  await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
  await act(async () => vi.advanceTimersByTimeAsync(10 * 60000));
  vi.mocked(orderApi.checkCamera).mockRejectedValueOnce(new Error("Unavailable"));
  await click("Check order");
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
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await observe(80, 750);
  expect(orderApi.checkCamera).not.toHaveBeenCalled();
  await observe(80, 250);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
});

it("disables paid checks when the backend is not configured while allowing preview", async () => {
  vi.mocked(orderApi.cameraConfig).mockResolvedValue({ configured: false });
  await render(); await camera(); await click("Check order");
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
  expect(sampled(scene, frame(80), 3250, 3750)).toBe(false);
  expect(scene.sample(frame(80), 4000)).toBe(true);
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
  expect(sampled(scene, meal, 9250, 9750)).toBe(false);
  expect(scene.sample(meal, 10000)).toBe(true);
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

it("detects a small added packet while ignoring an isolated noisy pixel", () => {
  const scene = new SceneTrigger();
  const baseline = new Uint8Array(1024).fill(80);
  scene.sample(baseline, 0);
  const noise = baseline.slice(); noise[0] = 200;
  expect(sampled(scene, noise, 250, 2000)).toBe(false);
  const packet = baseline.slice();
  for (let row = 0; row < 4; row++) for (let col = 0; col < 8; col++) packet[row * 32 + col] = 200;
  expect(sampled(scene, packet, 2250, 2750)).toBe(false);
  expect(scene.sample(packet, 3000)).toBe(true);
});

it("shows an unexpected unidentified item as orange, matching the comparison verdict", () => {
  const state = checked();
  state.disposition = "needs_review";
  state.current_check!.verdict = "unsure";
  state.current_check!.discrepancies = [{ kind: "unexpected", message: "Not on the ticket: Drink", line_ids: [] }];
  expect(toScreenState(state).tone).toBe("amber");
});

it("keeps the exact submitted photo labeled with its ticket after selection changes", async () => {
  await render(); await camera(); await click("Check order");
  await render(ticket("second"));
  expect(container.querySelector(".camera-last-photo summary")?.textContent).toContain("FIRST");
  expect(container.querySelector(".camera-last-photo img")?.getAttribute("src")).toBe("data:image/jpeg;base64,cGhvdG8=");
});

it("rechecks uncertain results but respects manual corrections", async () => {
  const state = checked(); state.current_check!.verdict = "unsure";
  vi.mocked(orderApi.checkCamera).mockResolvedValueOnce(state);
  await render(); await camera();
  const automatic = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  expect(automatic.checked).toBe(true);
  await click("Check order");
  expect(automatic.checked).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  await render(ticket(), false, 1);
  expect(automatic.checked).toBe(false);
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

it("invalidates a photo if food moves away and returns, or sampling stops", () => {
  const frame = new Uint8Array(1024).fill(80);
  const guard = new SceneGuard(frame, 0);
  guard.sample(frame, 250); expect(guard.unchanged(250)).toBe(true);
  guard.sample(new Uint8Array(1024), 500);
  guard.sample(frame, 750); expect(guard.unchanged(750)).toBe(false);
  const stalled = new SceneGuard(frame, 0);
  stalled.sample(frame, 1500); expect(stalled.unchanged(1500)).toBe(false);
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
  await render(); await camera(); await click("Check order");
  await act(async () => vi.advanceTimersByTimeAsync(1500));
  if (kind === "motion") {
    vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(4096).fill(200) }) } as unknown as CanvasRenderingContext2D);
    await act(async () => vi.advanceTimersByTimeAsync(250));
  } else if (kind === "hidden") {
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  } else if (kind === "closed") await click("Close camera");
  const pending = checked(); pending.current_check!.execution_status = "awaiting_confirmation"; pending.current_check!.verdict = null;
  await act(async () => resolve(pending));
  expect(orderApi.confirmCamera).toHaveBeenCalledWith(expect.objectContaining({ scene_unchanged: kind === "still" }));
  expect(toScreenState(onResult.mock.calls[0][0]).tone).toBe(kind === "still" ? "green" : "amber");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const events = readCvLogs()[0].events.map(event => event.message).join(" ");
  if (kind === "motion") expect(events).toContain("scene_changed");
  if (kind === "hidden") expect(events).toContain("tab_hidden");
  if (kind === "closed") expect(events).toContain("camera_stopped");
  if (kind === "hidden") {
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
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

it("revokes a result if the scene changes during confirmation without spending again", async () => {
  const pending = checked(); pending.current_check!.execution_status = "awaiting_confirmation";
  vi.mocked(orderApi.checkCamera).mockResolvedValue(pending);
  let resolve!: (state: OrderState) => void;
  vi.mocked(orderApi.confirmCamera).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockImplementationOnce(async () => {
    const rejected = checked(); rejected.current_check!.execution_status = "superseded"; rejected.disposition = "needs_review";
    return rejected;
  });
  await render(); await camera(); await click("Check order");
  await click("Close camera");
  const accepted = checked(); accepted.current_check!.verdict = "pass";
  await act(async () => resolve(accepted));
  expect(vi.mocked(orderApi.confirmCamera).mock.calls.map(call => call[0].scene_unchanged)).toEqual([true, false]);
  expect(toScreenState(onResult.mock.calls[0][0]).tone).toBe("amber");
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
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
  await observe(0); // First baseline is local only.
  await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await render(ticket("second"));
  await observe(80, 10000); // Untouched food cannot check the next ticket.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("Remove the previous order");
  await observe(200, 250); await observe(80); // Brief hand wave.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await observe(0, 3000); // Cleared view is observed without an AI call.
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("Place the next order");
  await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
  expect(vi.mocked(orderApi.checkCamera).mock.calls[1][0].order_id).toBe("second");
  await observe(80, 10000);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(4);
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

it("keeps manual checks available without an extra confirmation and respects opting out of automatic checks", async () => {
  await render(); await camera(); await click("Check order");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const automatic = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  await act(async () => automatic.click());
  await render(ticket("second"));
  await observe(0); await observe(80);
  expect(automatic.checked).toBe(false);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  await click("Check order");
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(2);
});

it("invalidates a snapshot when the ticket contents change without turning automatic mode off", async () => {
  await render(); await camera(); await observe(0); await observe(80);
  await render({ ...ticket(), order: { ...ticket().order, revision: 4 } });
  await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  const changed = ticket(); changed.order.lines[0].quantity = 2;
  await render(changed); await observe(80);
  expect(orderApi.checkCamera).toHaveBeenCalledTimes(1);
  expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
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
    observations: { schema_version: 1 as const, capture_id: "capture", targets: [{ target_id: "fries", status: "unsure" as const, observed_quantity: null, reason: "Covered" }], unexpected_items: [{ name: "Drink", quantity: 1 }], scene_uncertainty: "Hands in frame" },
  };
  vi.mocked(orderApi.checkCamera).mockResolvedValue({ ...checked(), diagnostics: diagnostic });
  await render(); await camera(); await click("CV logs");
  expect(container.querySelector('#camera-panel')!.hasAttribute("hidden")).toBe(true);
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
  expect(JSON.stringify(readCvLogs())).not.toContain("data:image");
  expect(readCvLogs()[0].diagnostics?.observations?.targets[0].status).toBe("unsure");
  await click("Clear logs");
  expect(logs.querySelector("img")).toBeNull();
});
