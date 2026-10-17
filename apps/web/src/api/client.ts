// Interface only: implement the HTTP/WebSocket client here when the API is ready.
import type {
  CaptureRequest,
  CheckAccepted,
  CreateCaptureRequest,
  CreateCheckRequest,
  OverrideRequest,
  StationEvent,
  StationSnapshot,
} from "./generated/contracts";

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
