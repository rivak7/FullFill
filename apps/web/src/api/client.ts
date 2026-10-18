// Order ingress is live. The camera/check command interface below is for the vision integration.
import type {
  Observations,
  VerificationTarget,
  CaptureRequest,
  CheckAccepted,
  CreateCaptureRequest,
  CreateCheckRequest,
  OverrideRequest,
  OrderSnapshot,
  OrderState,
  StationEvent,
  StationSnapshot,
} from "./generated/contracts";

export interface MenuEntry {
  item_id: string;
  name: string;
  description: string;
  price_cents: number;
  currency: string;
  available: boolean;
  archived: boolean;
  version: number;
  photo_id: string | null;
  photo_url: string | null;
}

export interface MenuSnapshot { revision: string; items: MenuEntry[] }
export interface MenuPhoto { data_base64: string }
export interface MenuEdit { item_id: string; name: string; price_cents: number; available: boolean; archived: boolean; version: number; photo?: MenuPhoto }
export interface OrderStatusEdit { worker_id: string; status: "unfulfilled" | "unsure" | "fulfilled"; expected_revision: number }

export interface CreateOrderInput {
  items: { item_id: string; quantity: number }[];
  menu_revision?: string;
  quote?: string;
}

export interface CameraDiagnostics {
  provider_called: boolean;
  image: string | null;
  targets: VerificationTarget[];
  references: { item_id: string; name: string; revision: number; role: "expected" | "alternative"; image: string | null }[];
  observations: Observations | null;
  timings_ms?: Record<string, number>;
  raw_answer?: string;
}
export type CameraResponse = OrderState & { diagnostics?: CameraDiagnostics | null };

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly diagnostics?: CameraDiagnostics) {
    super(message);
  }
}

// Configure this only when the deployed API has a separate origin. Never put credentials here.
const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const accessStorageKey = "fullfill.access.v1";
let accessKey = "";
try { accessKey = sessionStorage.getItem(accessStorageKey) ?? ""; } catch { /* In-memory access still works. */ }

export function setAccessKey(value: string) {
  accessKey = value;
  try {
    if (value) sessionStorage.setItem(accessStorageKey, value);
    else sessionStorage.removeItem(accessStorageKey);
  } catch { /* Keep the code in memory when storage is unavailable. */ }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), path === "/menu/items" || path === "/checks/camera" ? 60000 : 20000);
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  try {
    const response = await fetch(`${apiBase}/v1${path}`, {
      ...options,
      cache: "no-store",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(accessKey ? { Authorization: `Bearer ${accessKey}` } : {}), ...options.headers },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) {
        setAccessKey("");
        window.dispatchEvent(new Event("fullfill:access-required"));
      }
      throw new ApiError(
        typeof data?.detail === "string" ? data.detail : "The request could not be completed. Please retry.",
        response.status,
        data?.diagnostics,
      );
    }
    if (data === null) throw new Error("The API returned an unreadable response.");
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new Error("Can't reach FullFill. Check that the backend is running, then retry.");
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

export const orderApi = {
  cameraConfig: (signal?: AbortSignal) => request<{ configured: boolean }>("/checks/camera/config", { signal }),
  checkCamera: (body: { worker_id: string; order_id: string; expected_revision: number; photo: MenuPhoto; boxes?: boolean; photos?: boolean; confirmed?: boolean }, key: string) => request<CameraResponse>("/checks/camera", {
    method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body),
  }),
  confirmCamera: (body: { worker_id: string; order_id: string; check_id: string; expected_revision: number; scene_unchanged: boolean }) => request<OrderState>("/checks/camera/confirm", {
    method: "POST", body: JSON.stringify(body),
  }),
  claim: (id: string, body: { worker_id: string; expected_revision: number; release?: boolean }) => request<OrderState>(`/orders/${encodeURIComponent(id)}/claim`, {
    method: "POST", body: JSON.stringify(body),
  }),
  session: (scope: "order" | "kitchen" = "order", signal?: AbortSignal) => request<{ required: boolean; authenticated: boolean; role: "order" | "kitchen" | null }>(`/session?scope=${scope}`, { signal }),
  menu: (signal?: AbortSignal) => request<MenuSnapshot>("/menu/current", { signal }),
  managedMenu: (signal?: AbortSignal) => request<MenuSnapshot>("/menu/manage", { signal }),
  saveMenu: (body: MenuEdit, key: string) => request<MenuSnapshot>("/menu/items", {
    method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body),
  }),
  station: (signal?: AbortSignal) => request<StationSnapshot>("/stations/main/refresh", { method: "POST", signal }),
  clearStation: () => request<StationSnapshot>("/stations/main/clear", { method: "POST" }),
  setStatus: (id: string, body: OrderStatusEdit, key: string) => request<OrderState>(`/orders/${encodeURIComponent(id)}/status`, {
    method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body),
  }),
  prepare: (body: CreateOrderInput, key: string) => request<CreateOrderInput>("/orders/prepare", {
    method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body),
  }),
  create: (body: CreateOrderInput, key: string) => request<OrderSnapshot>("/orders", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify(body),
  }),
};

export interface StationApi {
  getStation(stationId: string): Promise<StationSnapshot>;
  requestCapture(
    stationId: string,
    request: CreateCaptureRequest,
    idempotencyKey: string,
  ): Promise<CaptureRequest>;
  startCheck(request: CreateCheckRequest, idempotencyKey: string): Promise<CheckAccepted>;
  confirm(orderId: string, request: OverrideRequest, idempotencyKey: string): Promise<void>;
  subscribe(
    stationId: string,
    after: string | null,
    onEvent: (event: StationEvent) => void,
  ): () => void;
}
