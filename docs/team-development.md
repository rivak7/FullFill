# Working independently

[order-checker.md](../order-checker.md) is the main plan.
[system-design.md](system-design.md) describes the target implementation.
This checkout now contains **scaffolding and interfaces only**.

## What is here

- Python 3.13 workspace with API, capture, and contracts packages.
- FastAPI app entry point and empty route modules.
- Minimal React/TypeScript entry point; no station screens yet.
- Pydantic data models, generated JSON Schema/TypeScript, and Python/TypeScript interfaces.
- Unimplemented Perceptron/fake adapters and a decision-rule function signature.
- Package locks and setup/build commands.

There are no working order endpoints, camera pipeline, replay client, fake workflow,
Perceptron calls, evaluation runner, database, WebSocket server, or Photon integration.
The API's empty docs and the frontend placeholder are expected.
A stub raises `NotImplementedError` when called; it never fabricates a successful check.

## Ownership and first implementation work

| Area | Files to work in | First work |
| --- | --- | --- |
| Station UI — William | `apps/web/src/features/`, `apps/web/src/api/client.ts` | Station, queue, and catalog screens; implement the client or a local mock of the same interface |
| Capture — William | `apps/capture/fullfill_capture/` | Camera/replay source, stillness trigger, QR/crop, and HTTP client |
| API/workflow — Roy | `apps/api/fullfill/http/`, `application/`, `domain/`, `ports/` | Order/check routes and orchestration, using the agreed contracts |
| Vision/Photon — Roy | `apps/api/fullfill/adapters/`, `apps/photon_bridge/` | Wrap Perceptron in `VisionProvider`; messaging uses `Notifier` |
| Evaluation — Rishabh | `eval/`, `fixtures/`, `tests/` | T1–T3 harness and labeled cases using the same vision interface |
| Contracts — shared | `packages/contracts/fullfill_contracts/` | Agree changes with affected teammates, regenerate both outputs |

The original root `config.py`, `camera_input_number.py`, and `requirements.txt` are
preserved. Run the camera probe from the repository root when you deliberately want
camera access. It is not imported by the scaffold. Keep future existing vision code in
place and call it from `adapters/vision/perceptron.py`; there is no need to rewrite its
internals to adopt the interface.

The workspace manifests are the dependency source for new packages. The root requirements
file remains the legacy setup path; dependencies are not silently copied into every package.
Install camera dependencies explicitly with `uv sync --inexact --package fullfill-capture --extra camera`.
An isolated capture environment needs only that package and its contracts, not the API or a vision SDK.

## Run the entry points

Requires Python 3.13, uv, and Node.js 22.12+ with npm.

```sh
make setup
make dev-api  # Terminal 1: http://127.0.0.1:8000/docs (empty route scaffold)
make dev-web  # Terminal 2: Vite prints its local URL (placeholder page)
```

No camera, API key, or messaging account is needed for these entry points.
There is deliberately no all-in-one working demo yet.

`make contracts` exports the Python models and regenerates TypeScript. Commit the model
change and both generated files together. Never hand-edit generated files.
`make check` checks Python syntax/style, generated-file drift, and the frontend build.
`make build` builds only the placeholder frontend; it does not create a station deployment.

## Interface agreements

| Boundary | Contract |
| --- | --- |
| Camera source | `CaptureSource.capture() -> ImageInput`; `close()` releases resources |
| Camera → API | Multipart image + `CaptureMetadata` → `CaptureReceipt`; submit `CreateCheckRequest` separately |
| API → vision | `VisionProvider.inspect(VisionInput) -> Observations` |
| Pure comparison | `compare_order(OrderSnapshot, Observations) -> Comparison` |
| API → browser | `StationSnapshot`, `CheckResult`, and WebSocket `StationEvent` |
| API → messaging | `Notifier.send(Notification) -> DeliveryResult` |
| API → persistence | Repository protocols in `fullfill/ports/repositories.py` |

These types define structure, not completed business validation. The workflow still needs
target-coverage checks, quantity/status consistency, revision guards, duplicate handling,
and retention enforcement. Raw image inputs are Python dataclasses; image bytes are not
part of the browser's JSON contract.

## Planned routes — not implemented

| Route | Request / response |
| --- | --- |
| `GET /v1/orders` | List of `OrderSnapshot` |
| `GET /v1/stations/{id}` | `StationSnapshot` |
| `POST /v1/stations/{id}/capture-requests` | `CreateCaptureRequest` → `CaptureRequest` |
| `GET /v1/stations/{id}/capture-requests` | List of pending `CaptureRequest` |
| `POST /v1/captures` | Image + `CaptureMetadata` → `CaptureReceipt` |
| `POST /v1/checks` | `CreateCheckRequest` → `202 CheckAccepted` |
| `GET /v1/checks/{id}` | `CheckResult` |
| `POST /v1/orders/{id}/overrides` | `OverrideRequest` → acknowledgement |
| `WS /v1/stations/{id}/events` | `StationEvent`; cursor/reconnect behavior follows system design |

Use an `Idempotency-Key` header for mutation retries when implementing the routes.
Catalog/reference commands and provider-specific transport need their own implementation
contracts as those pieces are built; `MenuItem` and `ReferenceSet` are their shared data types.

Use separate branches and small pull requests. Each teammate can start within their folder;
changes to shared types or route semantics need agreement from the consumers first.
