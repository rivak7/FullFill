// Order ingress is live. The camera/check command interface below is for the vision integration.
import type {
  CaptureRequest,
  CheckAccepted,
  CreateCaptureRequest,
  CreateCheckRequest,
  OverrideRequest,
  OrderSnapshot,
  StationEvent,
  StationSnapshot,
} from "./generated/contracts";

export interface MenuEntry {
  item_id: string;
  name: string;
  description: string;
  price_cents: number;
  currency: string;
}

export interface CreateOrderInput {
  items: { item_id: string; quantity: number }[];
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

// Configure this only when the deployed API has a separate origin. Never put credentials here.
const apiBase = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 20000);
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  try {
    const response = await fetch(`${apiBase}/v1${path}`, {
      ...options,
      cache: "no-store",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        typeof data?.detail === "string" ? data.detail : "The request could not be completed. Please retry.",
        response.status,
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
  menu: (signal?: AbortSignal) => request<MenuEntry[]>("/menu", { signal }),
  station: (signal?: AbortSignal) => request<StationSnapshot>("/stations/main", { signal }),
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
