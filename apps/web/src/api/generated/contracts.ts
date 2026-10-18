/* Generated from Python contracts. Run make contracts; do not edit. */

export type CameraProfileId = string;
export type CapturedAt = string;
export type Purpose = "check" | "reference";
export type QrCandidate = string | null;
export type RequestId = string | null;
export type SceneSequence = number;
export type SchemaVersion = 1;
export type SessionId = string;
export type StationId = string;
export type CaptureId = string;
export type DispositionRevision = number;
export type OrderId = string;
export type OrderRevision = number;
export type Purpose1 = "check" | "reference";
export type RequestId1 = string;
export type StationId1 = string;
export type CheckId = string;
export type DispositionRevision1 = number;
export type ExecutionStatus = "queued";
export type CaptureId1 = string;
export type ExpectedDispositionRevision = number;
export type OrderId1 = string;
export type OrderRevision1 = number;
export type SchemaVersion1 = 1;
export type StationId2 = string;
export type CaptureId2 = string;
export type CheckId1 = string;
export type CompletedAt = string | null;
export type ExpectedQuantity = number | null;
export type Kind = "missing" | "unexpected" | "wrong_item" | "unidentified" | "unsure";
export type LineIds = string[];
export type Message = string;
export type MissingQuantity = number | null;
export type ObservedQuantity = number | null;
export type TargetId = string | null;
export type Discrepancies = Discrepancy[];
export type Disposition = "pending" | "verified" | "needs_review" | "overridden";
export type DispositionRevision2 = number;
export type ErrorCode = string | null;
export type ExecutionStatus1 = "queued" | "running" | "awaiting_confirmation" | "completed" | "failed" | "superseded";
export type OrderId2 = string;
export type OrderRevision2 = number;
export type SchemaVersion2 = 1;
export type Verdict = ("pass" | "fail" | "unsure") | null;
export type Discrepancies1 = Discrepancy[];
export type Verdict1 = "pass" | "fail" | "unsure";
export type Purpose2 = "check" | "reference";
export type ErrorCode1 = string | null;
export type ProviderReceipt = string | null;
export type Status = "sent" | "failed";
export type ItemId = string;
export type LabelAliases = string[];
export type Name = string;
export type VerificationMode = "visible_item" | "label" | "container_count";
export type DeduplicationKey = string;
export type Kind1 = "error" | "override" | "shift_summary";
export type Message1 = string;
export type NotificationId = string;
export type CaptureId3 = string;
export type CompletionTokens = number | null;
export type LatencyMs = number;
export type Model = string;
export type PromptTokens = number | null;
export type PromptVersion = string;
export type Provider = string;
export type RequestId2 = string | null;
export type SceneUncertainty = string | null;
export type SchemaVersion3 = 1;
/**
 * @minItems 1
 */
export type Targets = [TargetObservation, ...TargetObservation[]];
export type XMax = number;
export type XMin = number;
export type YMax = number;
export type YMin = number;
/**
 * @maxItems 32
 */
export type Boxes = BoundingBox[];
export type LabelText = string | null;
export type ObservedQuantity1 = number | null;
export type Reason = string | null;
export type Status1 = "present" | "missing" | "unsure";
export type TargetId1 = string;
/**
 * @maxItems 32
 */
export type Boxes1 = BoundingBox[];
export type InsteadOfTargetId = string | null;
export type ItemId1 = string | null;
export type Name1 = string;
export type Quantity = number | null;
export type UnexpectedItems = UnexpectedItem[];
/**
 * @minItems 1
 */
export type Lines = [OrderLine, ...OrderLine[]];
export type ItemId2 = string;
export type LineId = string;
export type Name2 = string;
export type Quantity1 = number;
export type RequiresManualReview = boolean;
export type VerificationMode1 = "visible_item" | "label" | "container_count";
export type OrderId3 = string;
export type Revision = number;
export type SchemaVersion4 = 1;
export type CheckId2 = string;
export type ConfirmedTargetIds = string[];
export type ExpectedDispositionRevision1 = number;
export type OperatorReference = string;
export type OrderRevision3 = number;
export type ReasonCode = "worker_confirmed_present" | "manual_order_acceptance";
export type CameraProfileId1 = string;
/**
 * @minItems 1
 */
export type ImageAssetIds = [string, ...string[]];
export type ItemId3 = string;
export type Revision1 = number;
export type EventId = string;
export type EventType = "check.queued" | "check.completed" | "check.failed" | "order.updated" | "resync_required";
export type ExpiresAt = number;
export type WorkerId = string;
export type Disposition1 = "pending" | "verified" | "needs_review" | "overridden";
export type DispositionRevision3 = number;
export type SchemaVersion5 = 1;
export type StationId3 = string;
export type EventCursor = string | null;
export type Orders = OrderState[];
export type SchemaVersion6 = 1;
export type StationId4 = string;
export type ExpectedQuantity1 = number;
export type ItemId4 = string;
export type LabelAliases1 = string[];
/**
 * @minItems 1
 */
export type LineIds1 = [string, ...string[]];
export type Name3 = string;
export type TargetId2 = string;
export type VerificationMode2 = "visible_item" | "label" | "container_count";

/**
 * Schema bundle only, not an API request.
 */
export interface FullFillContracts {
  capture_metadata: CaptureMetadata;
  capture_receipt: CaptureReceipt;
  capture_request: CaptureRequest;
  check_accepted: CheckAccepted;
  check_request: CreateCheckRequest;
  check_result: CheckResult;
  comparison: Comparison;
  create_capture_request: CreateCaptureRequest;
  delivery_result: DeliveryResult;
  menu_item: MenuItem;
  notification: Notification;
  observations: Observations;
  order: OrderSnapshot;
  override: OverrideRequest;
  references: ReferenceSet;
  station_event: StationEvent;
  station_snapshot: StationSnapshot;
  vision_target: VerificationTarget;
}
export interface CaptureMetadata {
  camera_profile_id: CameraProfileId;
  captured_at: CapturedAt;
  purpose: Purpose;
  qr_candidate?: QrCandidate;
  request_id?: RequestId;
  scene_sequence: SceneSequence;
  schema_version?: SchemaVersion;
  session_id: SessionId;
  station_id: StationId;
}
export interface CaptureReceipt {
  capture_id: CaptureId;
  order_context?: OrderContext | null;
}
export interface OrderContext {
  disposition_revision: DispositionRevision;
  order_id: OrderId;
  order_revision: OrderRevision;
}
export interface CaptureRequest {
  order_context?: OrderContext | null;
  purpose: Purpose1;
  request_id: RequestId1;
  station_id: StationId1;
}
export interface CheckAccepted {
  check_id: CheckId;
  disposition_revision: DispositionRevision1;
  execution_status?: ExecutionStatus;
}
export interface CreateCheckRequest {
  capture_id: CaptureId1;
  expected_disposition_revision: ExpectedDispositionRevision;
  order_id: OrderId1;
  order_revision: OrderRevision1;
  schema_version?: SchemaVersion1;
  station_id: StationId2;
}
export interface CheckResult {
  capture_id: CaptureId2;
  check_id: CheckId1;
  completed_at?: CompletedAt;
  discrepancies?: Discrepancies;
  disposition: Disposition;
  disposition_revision: DispositionRevision2;
  error_code?: ErrorCode;
  execution_status: ExecutionStatus1;
  order_id: OrderId2;
  order_revision: OrderRevision2;
  schema_version?: SchemaVersion2;
  verdict?: Verdict;
}
export interface Discrepancy {
  expected_quantity?: ExpectedQuantity;
  kind: Kind;
  line_ids?: LineIds;
  message: Message;
  missing_quantity?: MissingQuantity;
  observed_quantity?: ObservedQuantity;
  target_id?: TargetId;
}
export interface Comparison {
  discrepancies?: Discrepancies1;
  verdict: Verdict1;
}
export interface CreateCaptureRequest {
  order_context?: OrderContext | null;
  purpose: Purpose2;
}
export interface DeliveryResult {
  error_code?: ErrorCode1;
  provider_receipt?: ProviderReceipt;
  status: Status;
}
export interface MenuItem {
  item_id: ItemId;
  label_aliases?: LabelAliases;
  name: Name;
  verification_mode?: VerificationMode;
}
export interface Notification {
  deduplication_key: DeduplicationKey;
  kind: Kind1;
  message: Message1;
  notification_id: NotificationId;
}
export interface Observations {
  capture_id: CaptureId3;
  provider?: ProviderMetadata | null;
  scene_uncertainty?: SceneUncertainty;
  schema_version?: SchemaVersion3;
  targets: Targets;
  unexpected_items?: UnexpectedItems;
}
export interface ProviderMetadata {
  completion_tokens?: CompletionTokens;
  latency_ms: LatencyMs;
  model: Model;
  prompt_tokens?: PromptTokens;
  prompt_version: PromptVersion;
  provider: Provider;
  request_id?: RequestId2;
}
export interface TargetObservation {
  boxes?: Boxes;
  label_text?: LabelText;
  observed_quantity?: ObservedQuantity1;
  reason?: Reason;
  status: Status1;
  target_id: TargetId1;
}
/**
 * Coordinates on the order image, normalized to a 0–1000 grid.
 */
export interface BoundingBox {
  x_max: XMax;
  x_min: XMin;
  y_max: YMax;
  y_min: YMin;
}
export interface UnexpectedItem {
  boxes?: Boxes1;
  instead_of_target_id?: InsteadOfTargetId;
  item_id?: ItemId1;
  name: Name1;
  quantity?: Quantity;
}
export interface OrderSnapshot {
  lines: Lines;
  order_id: OrderId3;
  revision: Revision;
  schema_version?: SchemaVersion4;
}
export interface OrderLine {
  item_id: ItemId2;
  line_id: LineId;
  name: Name2;
  quantity: Quantity1;
  requires_manual_review?: RequiresManualReview;
  verification_mode?: VerificationMode1;
}
export interface OverrideRequest {
  check_id: CheckId2;
  confirmed_target_ids?: ConfirmedTargetIds;
  expected_disposition_revision: ExpectedDispositionRevision1;
  operator_reference: OperatorReference;
  order_revision: OrderRevision3;
  reason_code: ReasonCode;
}
export interface ReferenceSet {
  camera_profile_id: CameraProfileId1;
  image_asset_ids: ImageAssetIds;
  item_id: ItemId3;
  revision: Revision1;
}
export interface StationEvent {
  event_id: EventId;
  event_type: EventType;
  order_state?: OrderState | null;
  schema_version?: SchemaVersion5;
  station_id: StationId3;
}
export interface OrderState {
  claim?: OrderClaim | null;
  current_check?: CheckResult | null;
  disposition: Disposition1;
  disposition_revision: DispositionRevision3;
  order: OrderSnapshot;
}
export interface OrderClaim {
  expires_at: ExpiresAt;
  worker_id: WorkerId;
}
export interface StationSnapshot {
  event_cursor?: EventCursor;
  orders?: Orders;
  schema_version?: SchemaVersion6;
  station_id: StationId4;
}
export interface VerificationTarget {
  expected_quantity: ExpectedQuantity1;
  item_id: ItemId4;
  label_aliases?: LabelAliases1;
  line_ids: LineIds1;
  name: Name3;
  target_id: TargetId2;
  verification_mode?: VerificationMode2;
}
