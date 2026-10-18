# FullFill

FullFill is a DubHacks '26 prototype for checking takeout orders before they leave
the packing station. The goal is to compare a camera photo with the ticket and
flag missing, extra, or uncertain items using Perceptron and reference photos of
the restaurant's menu.

**Today, the app supports Square Sandbox ordering, a shared menu editor, and a
live kitchen queue with browser camera checks.** The browser captures selected
frames, the backend calls Perceptron, and compact results persist in Square.

## What works

| Area | Current behavior |
| --- | --- |
| Order entry | Browse the shared menu and create Square Sandbox orders with server-owned prices and retry-safe checkout. |
| Kitchen queue | Refresh one second after each successful response; requests stay sequential and failed refreshes back off from 3 to 30 seconds. Show open, nonempty tickets newest first. Staff can fulfill, flag for review, or reopen tickets; completion advances upward to the next unresolved ticket. New arrivals preserve the current selection. |
| Menu management | Add items with a required photo, replace photos, edit names/prices, mark items sold out, and delete items. Photos persist in Square Catalog. Ordering screens refresh every five seconds and when returning to the tab. |
| Shared state | Orders and menu edits persist in Square across browsers and API instances using the same Sandbox account and location. Conflicting menu edits require a refresh. |
| Vision adapter | Send an order photo and labeled reference photos to Perceptron Mk1.5; validate structured observations. Browser checks require a reference for every ticket item. Expected quantities are kept out of the model prompt. |
| Browser camera | Enable a local video preview, then check the selected ticket manually or opt into checks after movement settles. No Python camera installation is needed. Preview makes no Perceptron calls. |
| Comparison rules | Exact, clearly visible counts pass; definite shortages/excesses fail; ambiguous identity/counts, unreadable required labels, unknown extras, poor camera views, and failed checks require review. A clear mismatch takes precedence over uncertainty about another item; an unusable whole-scene view invalidates all counts. |
| Station preview | Explore hardcoded checking, pass, fail, unsure, and error states at `/demo` in the combined frontend. |
| Evaluation | Run photo-based latency, order-accuracy, and lookalike/label checks, including names-only versus reference-photo comparisons and JSONL logging. |

New orders start `pending`; manual review sets `needs_review` and manual fulfillment
sets `overridden`. Camera passes set `verified`; failed/uncertain checks never
fabricate a pass. The app does not charge payments. Manual and camera status persist in Square
metadata and is invalidated when ticket items change; saves reject stale revisions.

The queue has a soft limit of 10 tickets. Refresh removes the oldest fulfilled
tickets above that limit, while retaining all unresolved tickets. Newly completed
tickets stay for at least two minutes so staff can undo mistakes; the cap can be
exceeded during this grace period. Cleanup and
manual statuses leave Square's payment and native fulfillment state unchanged.
Deleted menu items are archived in Square and hidden from the menu, with no
restore option in the UI. Existing starter items can be edited without photos;
new items require one. Camera checks include saved photos for ticket items and
up to six alternative menu items selected using local image and name similarity.

The capture package still contains interfaces and TODOs for camera/replay sources,
stillness triggering, QR decoding, cropping, and uploading. The browser uses its
own lightweight frame-difference trigger; it does not execute the Python camera scripts.
The planned asynchronous capture/check API, WebSocket updates, richer reference
enrollment, and Photon notifications remain unfinished. Vision checks
can only assess visible items or readable labels, not hidden fillings or modifiers
such as “no onion.” A saved menu photo is a visual reference, not model training.

Camera checks require `PERCEPTRON_API_KEY` on the backend. Keep it out of `VITE_`
variables. Open the kitchen page and enable the camera once. **Automatic checks**
start enabled and stay enabled as fulfilled tickets advance through the queue.
Place the first order in view after the preview starts; a changed view that stays
still for 1.5 seconds triggers a check. **Check order** remains an optional manual
capture with no separate handoff confirmation.

For subsequent tickets, the browser observes two transitions: the previous view
changes and stays stable for at least 750 ms, then a replacement view changes
again and settles for 1.5 seconds. The intermediate view makes no model call.
Clear the packing area briefly between orders. This allows identical meals to be
checked separately while suppressing untouched food and brief hand waves. It is
a motion heuristic, not proof that the area is empty: a prolonged obstruction or
lighting change can fool it, and a swap with no visible gap can be missed. Manual
checks remain available if the transition was missed. Hidden tabs, sampling gaps,
and camera stops discard incomplete handoff evidence. Initial startup/reload
establishes a fresh baseline rather than automatically submitting a still scene.
There are no application spending caps or forced cooldowns for browser checks.
Only one check runs at a time for a ticket, duplicate requests remain idempotent,
and failures are not automatically retried. Expand **Check activity** to count
attempts over the last 5 minutes, hour, or 24 hours. Timestamp-only history survives
refreshes and menu visits and includes other tabs on this browser/site. It includes
failed requests, so it is not a provider billing total or an all-devices counter.
Older timestamps are discarded when history is read; clearing browser data resets it.
Camera images stay in memory; only compact observations and hashes persist in Square.
Keep the page visible and the computer awake. Preview frames stay local; automatic
checks send selected snapshots only after the trigger conditions are met.

Each kitchen screen reserves its selected unresolved order for two minutes,
renewing while it works. Other screens skip that ticket and show “Working on
another screen.” Switching releases unfinished work; closing or losing a screen
lets the reservation expire. This coordinates software screens, not physical
staff activity; both sites use the same shared demo access code.

### Camera decisions and corrections

The browser handles camera preview, cropping, movement detection, and stillness
without installing Python or OpenCV. Only a selected still image is uploaded to
the Vercel API, which calls Perceptron with the server-side key. Reference photos
identify menu items; they do not train the model or prove hidden ingredients.
Missing ticket references block the provider call and name the items needing photos.
Alternative selection uses a cheap retrieval heuristic, not a trained identity
classifier. All available active menu photos participate in retrieval; selected
alternatives travel in the same model request. Downloads are cached by URL and
catalog version. Broken reference downloads fail visibly before a paid call.
Ticket lines with different options stay separate; variations, modifiers, and
special instructions require staff confirmation even when the counts match.

Perceptron reports observed counts and uncertainty; application rules decide the
status. The expected counts remain outside the model prompt. Green means a clear
snapshot match and advances upward in the queue. Red names definite shortages or
excesses, or a confidently identified wrong menu item. A clear substitution can
show both the missing item and what appeared instead. Unknown objects remain
explicitly unidentified, without forcing a menu match. Orange names uncertain
items or gives an instruction for improving the
camera view. An API error is orange, never evidence that food is missing. Partial,
contradictory, malformed, or stale results cannot produce a green screen.

Camera results first persist as `awaiting_confirmation`. The capturing browser
keeps sampling during inference, including manual checks, and confirms only if
its view stayed unchanged. Movement, a hidden tab, camera loss, or a sampling gap
invalidates the photo; missing confirmation expires to orange after 15 seconds.
Confirmation also compares the current menu reference fingerprint against the one
used for inference. Changed photos, names, modes, or catalog versions require a
fresh check; a menu outage cannot approve the result. Catalog and order writes
are separate operations, so a change after the comparison is still possible.
This is a motion heuristic, not proof against subtle visual changes. The final
network acknowledgment also has a small race window; detected movement requests
revocation of that same result without another model call.

Unexpected-item names and quantities are stored in full, using compression and
line-item metadata overflow when necessary. Storage failure requires review;
results never silently drop extra items to fit.

If the result looks wrong, expand **Last photo** to inspect the exact submitted
frame and its ticket ID. Reposition items and check again, or use the existing
manual fulfillment/review controls. A new **Undo** button reopens a just-completed
ticket and selects it again without calling Perceptron. Manual review/reopen
actions pause automatic checks; fulfilling a ticket keeps automatic mode running
for the next ticket. Manual decisions take precedence over an in-flight result; conflicting edits
from another screen require refresh instead of silently overwriting them.

Automatic checks pause on uncertainty or failure. They never retry a paid request
on their own. Each result describes the captured moment, not continuous proof of
the order's contents: keep one order entirely visible until the check finishes.
Closed bags, hidden fillings, and visually identical packaging need a readable
identifier or staff inspection. The app does not infer that the physical packing
area belongs to a ticket; staff must select the correct ticket.

These rules reduce avoidable mistakes; automated tests do not establish model
accuracy. Before relying on automatic completion, evaluate labeled examples from
the actual camera and menu, especially missing items, lookalikes, clutter, and
closed packaging. No numerical confidence threshold is presented as calibrated.

## Run locally

Use **Python 3.13**, **uv**, and **Node.js 22.12+ with npm**. The Python workspace
requires Python 3.13 specifically. Run commands from the repository root.

1. Install the locked dependencies:

   ```sh
   uv sync --locked --inexact
   npm --prefix apps/web ci
   ```

2. Copy `.env.example` to `.env` and set your Square Sandbox credentials:

   ```dotenv
   SQUARE_ENVIRONMENT=sandbox
   SQUARE_ACCESS_TOKEN=your_sandbox_access_token
   SQUARE_LOCATION_ID=your_sandbox_location_id
   ```

   `.env` is ignored by Git. `SQUARE_APPLICATION_ID` is reserved for future
   integrations and is not required for the current server-side order calls.

3. Seed missing starter menu items in the configured Sandbox location:

   ```sh
   uv run python scripts/seed_square_menu.py
   ```

   This writes to Square Catalog and preserves existing items and edits, including
   archived items. The starter menu is defined in
   [`demo-menu.json`](apps/api/fullfill/adapters/orders/demo-menu.json).

4. Start the API:

   ```sh
   uv run --no-sync uvicorn fullfill.main:create_app --factory --reload --env-file .env --host 127.0.0.1 --port 8000
   ```

5. In another terminal, start the frontend:

   ```sh
   npm --prefix apps/web run dev
   ```

Open these URLs (assuming Vite's default port is available):

| URL | Screen |
| --- | --- |
| `http://127.0.0.1:5173/order` | Customer order entry |
| `http://127.0.0.1:5173/fulfill` | Kitchen queue and **Menu** tab |
| `http://127.0.0.1:5173/demo` | Static vision-state preview; no credentials or hardware required |
| `http://127.0.0.1:8000/docs` | Interactive API documentation |

`/` opens the kitchen queue. Place a Sandbox order at `/order`, then verify its
ticket ID and quantities at `/fulfill`. Order/menu pages need Square credentials;
they show configuration/provider failures instead of substituting fake orders.
No camera or Perceptron key is needed for this flow. Menu photos can be uploaded
from files; **Take photo** requests camera permission only when clicked.

If Make is available, `make setup`, `make dev-api`, and `make dev-web` provide the
same setup and server commands. Restart the API after changing `.env`.

For separate local sites, run `npm --prefix apps/web run dev:order` and
`npm --prefix apps/web run dev:fulfill` in separate terminals alongside the API.
They open directly at `/` on ports **5174** and **5175**, respectively. The Vite
development proxy forwards `/v1` requests to port 8000.

## Configuration and hosting

| Variable | Purpose |
| --- | --- |
| `SQUARE_ENVIRONMENT` | Set to `sandbox`; the current adapter rejects production configuration. |
| `SQUARE_ACCESS_TOKEN`, `SQUARE_LOCATION_ID` | Backend credentials/location for shared orders and catalog. |
| `FULLFILL_ACCESS_KEY` | Shared ordering and kitchen access code; at least 32 characters. Required on Vercel and optional locally. |
| `FULLFILL_WEB_ORIGINS` | Comma-separated exact frontend origins for API CORS when hosting sites separately. |
| `VITE_API_BASE_URL` | Public API origin, configured before frontend builds. Separate-site builds require an HTTPS URL. Local development uses the proxy by default. |
| `PERCEPTRON_API_KEY` | Required only for real vision/evaluation calls. |
| `PERCEPTRON_MODEL` | Optional model override; the vision adapter defaults to `perceptron-mk1.5`. |
| `CAMERA_INDEX` | Camera index used by the standalone evaluation photo-capture utility. |

Keep Square credentials, the Perceptron key, and the demo access code on the
backend. Never prefix secrets with `VITE_`, which exposes values in browser builds.
The hosted demo uses one shared bearer code stored per browser tab. The same code
opens ordering and kitchen screens, including menu editing and camera checks.
There are no separate role codes or individual user accounts.

The repository supports three Vercel projects: one FastAPI backend plus separate
order and kitchen sites. Separate builds use `build:order` and `build:fulfill`,
with output in `apps/web/dist/order` and `apps/web/dist/fulfill`. See
[deployment configuration](docs/vercel.md) for project settings and secrets.
The [Checks and deploy workflow](.github/workflows/scaffold.yml) runs `make check`
on pushes and pull requests; successful current-`main` runs deploy the API, order
site, then kitchen site when deployment credentials are configured.

## Project layout

| Path | Responsibility |
| --- | --- |
| `apps/web/` | React 19, TypeScript, and Vite; ordering, fulfillment, menu editing, and station preview. |
| `apps/api/` | FastAPI routes, the `OrderSource` boundary, Square adapters, Perceptron adapter, and pure comparison rules. |
| `apps/capture/` | Capture package interfaces and planned camera pipeline. OpenCV is an optional dependency. |
| `packages/contracts/` | Pydantic models and provider protocols; generated JSON Schema and TypeScript contracts. |
| `eval/` | Standalone photo capture, live vision evaluation, and offline evaluation tests. |
| `tests/`, `apps/web/tests/` | Python tests for orders, menu photos, hosted access, vision, and comparison; frontend tests for queue behavior and menu/photo editing. |
| `fixtures/`, `apps/photon_bridge/` | Placeholders for shared evaluation cases and optional messaging integration. |
| `scripts/` | Square menu seeding and contract export. |
| `app.py` | Vercel ASGI entry point; local development uses `fullfill.main:create_app`. |
| `config.py`, `camera_input_number.py` | Shared evaluation settings and the original camera probe. The probe opens cameras only when run explicitly. |

The current request flow is **browser → FastAPI → Square Orders/Catalog**. The
browser consumes FullFill models rather than raw Square responses. Evaluation
calls the Perceptron adapter and comparison rules directly; it does not pass
through the browser camera route. Browser checks use `POST /v1/checks/camera`;
their version-checked reservations and results are shared through Square metadata.

### Implemented API routes

All routes below use the `/v1` prefix. With an access code configured, API reads
and writes require `Authorization: Bearer <demo-code>`; `/session` reports access
state without requiring authentication. Both session scopes accept the same code.

| Method and path | Behavior |
| --- | --- |
| `GET /session` | Report whether demo access is required and the supplied code is valid. |
| `GET /menu/current`, `GET /menu/manage` | Read the shared menu and revision. |
| `POST /menu/items` | Create or edit a managed menu item using its version and an `Idempotency-Key`; creation requires a photo. |
| `POST /orders/prepare` | Validate a basket/menu revision and return a signed checkout; requires an `Idempotency-Key`. |
| `POST /orders` | Create the prepared order using the same checkout and idempotency key. |
| `GET /orders`, `GET /orders/{id}` | List eligible queue tickets or retrieve an order snapshot. |
| `POST /orders/{id}/claim` | Acquire, renew, or release a two-minute reservation using `worker_id` and `expected_revision`. |
| `POST /orders/{id}/status` | Save `unfulfilled`, `unsure`, or `fulfilled` using `worker_id`, `expected_revision`, and an `Idempotency-Key`. |
| `GET /stations/{id}` | Read the queue as a station snapshot, including manual status and camera results. |
| `POST /stations/{id}/refresh` | Remove fulfilled overflow above the soft limit and return the latest snapshot. |
| `GET /checks/camera/config` | Report whether a server key is configured; does not call Perceptron or reveal the key. |
| `POST /checks/camera` | Accept `{order_id, worker_id, expected_revision, photo: {data_base64}}` with `Idempotency-Key`; reserve one check, call Perceptron once, and return the pending `OrderState`. |
| `POST /checks/camera/confirm` | Confirm the same `check_id`, worker, and revision with `scene_unchanged`; stale/changed scenes require review. |

There is also a legacy `GET /v1/menu` endpoint, which can return the starter menu
when Square credentials are absent. It does not make live ordering available.
See [the Square integration guide](docs/square-demo.md) for request examples,
checkout retry behavior, queue limits, and the vision handoff.

## Development and validation

Run `make contracts` after editing shared Python models. Commit both generated
outputs with the model changes; do not edit them by hand. Without Make:

```sh
uv run --no-sync python scripts/export_contracts.py
npm --prefix apps/web run generate:contracts
```

Run `make check` before pushing. It checks Python lint/formatting and compilation,
runs Python and frontend tests, regenerates contracts and checks for drift, then
builds all three frontend variants. Its `api.example.invalid` URL is only a
build-check value.

For focused offline validation:

```sh
uv run --no-sync pytest -q tests
npm --prefix apps/web test
npm --prefix apps/web run build
```

These tests mock external calls and need no Square/Perceptron credentials or
camera. They do not establish live model accuracy, camera behavior, or deployment
health.

### Vision evaluation

See [the evaluation guide](eval/README.md) for reference photos, a case manifest,
and T1–T3 scoring. Evaluation uses OpenCV to prepare photos, even without a live
camera. Install the optional dependency and run the separate offline harness
tests (these are not included in `make check`):

```sh
uv sync --inexact --package fullfill-capture --extra camera
uv run --no-sync pytest -q eval/test_eval.py
```

After preparing `eval/manifest.json` and its images:

```sh
uv run --no-sync python -m eval.run t2 --dry-run --mode both
```

The dry run builds requests without calling Perceptron. Live evaluation requires
`PERCEPTRON_API_KEY`, consumes API credits, and records calls in `logs/eval/`.
It uses cooldowns, a per-run cap, a lifetime evaluation cap
(`EVAL_MAX_TOTAL_CALLS`, default 200), and stops after three consecutive failures.
For camera photo collection, follow the capture commands in that guide using the
same workspace environment.

## Plans and license

[order-checker.md](order-checker.md) contains the original pitch and hackathon
plan; [system-design.md](docs/system-design.md) describes the target architecture.
The [team development guide](docs/team-development.md) records ownership and
interface agreements. Some older scaffold notes in that guide and folder READMEs
predate the implemented order/menu flow; use the current status above when
assessing what runs today.

FullFill is licensed under the [MIT License](LICENSE).
