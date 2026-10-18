# Square order entry and fulfillment

The order entry screen creates orders in Square Sandbox. The fulfillment screen
polls that same location one second after each successful response. Square holds the orders; they are
not stored in a browser or an API process's memory. The current integration does
not charge payments. Staff can run camera checks, mark tickets fulfilled,
flag them for review, or reopen them from the kitchen screen.

## Run locally

1. Install the workspace with `make setup` (Python 3.13 and Node 22.12+).
2. Set `SQUARE_ENVIRONMENT=sandbox`, `SQUARE_ACCESS_TOKEN`, and
   `SQUARE_LOCATION_ID` in the root `.env`. `SQUARE_APPLICATION_ID` may stay there
   for future integrations; these server-side order calls don't require it.
3. Run `uv run python scripts/seed_square_menu.py` once to add missing starter items
   to Square Catalog. This preserves any existing edits, including archived items.
4. Run `make dev-api`. It reads `.env`; restart it after changing credentials.
5. In another terminal run `make dev-web`.
6. Open `http://127.0.0.1:5173/order` and `http://127.0.0.1:5173/fulfill`.
7. Place an order. It joins the fulfillment queue automatically. Select its
   ticket to see the item quantities. New arrivals never replace a selected ticket.

The original screen-state examples are available separately at `/demo`.
The `/` route opens the live fulfillment queue.

## Edit the shared menu

Open **Menu** on the kitchen site. There is no separate menu editing code. New items
require a name, price, and photo. Choose **Take photo** to capture from a camera, or
**Upload photo** to choose an existing JPEG, PNG, or WebP. The photo preview is saved
with the item; **Replace photo** or **Take photo** replaces it on the next save.
Existing items can be renamed, repriced, marked sold out, or deleted. Deleted items
leave the menu entirely; there is no Deleted view or restore option. Past orders
and the archived Square catalog record are kept.
Starter items without photos remain editable so their real photos can be added later.
The ordering screen refreshes every five seconds and when returning to the tab.
If a selected item changes, checkout pauses until the customer reviews the basket.
Unavailable items must be removed before placing a new order.

Menu data persists in Square Sandbox Catalog across computers and deployments.
Only FullFill-managed catalog items at the configured location are editable here.
Each variation's `user_data` holds the stable FullFill item ID, location, availability,
and verification mode. Version checks reject conflicting simultaneous edits.
New items still need vision reference enrollment; adding a menu item does not train
the vision checker. Existing burritos retain label verification.

Photos persist as Square Catalog images. Menu entries expose `photo_id` and
`photo_url`; browser camera checks send the relevant saved menu photos as references.
The browser resizes to at most 1920 pixels on the longest side, re-encodes to JPEG
without camera metadata, and keeps uploads below 1.5 MB. The backend validates the
actual image before uploading. `POST /v1/menu/items` accepts optional
`photo: {"data_base64": "..."}` (required for creation); omitting it preserves the
existing photo. Uploads use a separate idempotency key derived from the save key.
The image is attached only in the version-checked item save, so conflicting edits
cannot silently overwrite a photo. Replaced images and unsuccessful attachments
remain in Square's image library; deleting a menu item archives its catalog item.
See [Square's image API](https://developer.squareup.com/reference/square/catalog-api/create-catalog-image).

## Kitchen queue

Tickets appear newest at the top and oldest at the bottom in a scrollable list.
The order cards are red for unfulfilled, orange for needs review, and green for
fulfilled. The initial selection is the oldest unresolved ticket at the bottom.
**Fulfill order** saves a manual confirmation and moves upward to the nearest
unresolved ticket above the current one, skipping green cards and including orange
cards. For example, completing the fourth card from the top selects the third if
it is unresolved, rather than jumping to the top of the list. The same
advance occurs when another kitchen screen completes the selected order. New
arrivals never replace a selected ticket; completed history remains selectable.
When no unresolved tickets remain, the screen shows **All caught up**. If there
are only older unresolved tickets below the completed one, it shows **No newer
orders** and allows a manual selection; polling does not wrap back down the list.
New arrivals resume upward progress from the oldest of the newly arrived tickets.

The queue has a **soft limit of 10 tickets**. Above ten, a kitchen refresh removes
the oldest fulfilled tickets until ten remain or there are no fulfilled tickets
left. Unfulfilled and orange tickets are always retained, even above the limit.
Removal persists in Square metadata across screens and reloads; the Square order
itself remains retrievable and its payment and native fulfillment state do not change.

Manual status lives in Square order metadata, bound to a fingerprint of the ticket
items. Changed items or quantities invalidate the previous confirmation. Saves
require the displayed Square revision and an idempotency key: stale screens get a
409 instead of overwriting someone else's action, and lost responses can be retried.
Cleanup also checks the current status after version conflicts, protecting orders
reopened by another screen. Status changes appear elsewhere on the next one-second poll, plus request time.

## Two computers

For local development, each computer can run this checkout and a backend with
the same Square Sandbox account and location. Create orders on one computer and
open the fulfillment queue on the other. Each uses its own localhost URL; the
shared orders travel through Square, so no direct LAN connection is needed.
Credentials belong in each backend's ignored `.env`, never in browser code.

For separate hosted sites, follow [the Vercel setup](vercel.md). Both pages use the same hosted API. The
frontend defaults to `/v1` on its own origin. If the API is hosted separately,
set `VITE_API_BASE_URL` to its HTTPS origin before building the frontend and set
`FULLFILL_WEB_ORIGINS` on the backend to the exact frontend origin (comma-separated
for multiple origins). The local Vite proxy is development-only. The deployment
must route `/v1` to the backend and `/order` and `/fulfill` to the frontend.

The hosted demo uses HTTPS and separate ordering (`FULLFILL_ACCESS_KEY`) and staff
(`FULLFILL_KITCHEN_KEY`) codes. Only staff can read the queue, edit the menu,
change statuses, and run camera checks.
Each browser asks for that shared demo code. CORS restricts browser origins but
is not authentication. The local servers do not need to be exposed publicly.

## API and integration boundary

| Route | Behavior |
| --- | --- |
| `GET /v1/menu/current` | Returns the shared catalog menu and its revision |
| `GET /v1/menu/manage` | Reads the editable menu using the existing demo session |
| `POST /v1/menu/items` | Saves an item; requires the demo session and `Idempotency-Key` |
| `POST /v1/orders/prepare` | Validates the menu revision and returns a signed checkout |
| `POST /v1/orders` | Creates an order from that checkout with the same `Idempotency-Key` |
| `GET /v1/orders` | Lists non-archived, open, nonempty orders oldest first |
| `POST /v1/orders/{id}/status` | Saves `{status, expected_revision}` with `Idempotency-Key`; status is `unfulfilled`, `unsure`, or `fulfilled` |
| `GET /v1/orders/{id}` | Retrieves the shared `OrderSnapshot` for a vision consumer |
| `GET /v1/stations/main` | Returns those orders as a `StationSnapshot` |
| `POST /v1/stations/main/refresh` | Removes oldest fulfilled overflow and returns the station snapshot |

Preparation body example (use the revision returned by `/v1/menu/current`):

```json
{
  "menu_revision": "CURRENT_MENU_REVISION",
  "items": [
    {"item_id": "chicken_burrito", "quantity": 2},
    {"item_id": "fries", "quantity": 1},
    {"item_id": "drink", "quantity": 1}
  ]
}
```

Submit the entire preparation response, including its opaque `quote`, to
`POST /v1/orders` with the same idempotency key. Preparation does not create an order.
The server chooses prices. Whole-item quantities are required. The browser retains
the prepared checkout, original basket details, and idempotency key across reloads
in that tab. Retries send an identical Square request even if staff subsequently
change the menu, so a lost response cannot create another order or reprice it.
Prepared checkouts remain valid after menu edits; new checkouts use the current menu.
Rotating the Square credential invalidates outstanding signed checkouts.
An HTTP failure is shown explicitly and never substituted with fake orders.

The adapter reads every queue page without the former 2,000-record cutoff.
A warm API process caches the active queue, fetching changes by `updated_at` with
a two-minute overlap, including closed orders so they leave the cache. Concurrent
polls share one fetch. Cold starts and a ten-minute reconciliation still scan all
open history; large histories may therefore slow those rebuilds. Archived rows
are discarded from memory, and failed pages never publish a partial queue or
advance the synchronization timestamp. Square remains the persistent source.
Empty and terminal orders are excluded. Unsupported quantities produce a visible
error instead of being rounded or silently omitted. Order IDs, line IDs, and
Square revisions are retained. Customer records and payment details aren't sent
to the frontend.

The starter menu lives in `apps/api/fullfill/adapters/orders/demo-menu.json`; live
menu data comes from Square Catalog. Created lines store `fullfill_item_id` and
`fullfill_verification_mode` in Square metadata. Renaming or archiving an item never
rewrites existing order lines. Earlier
ad hoc sample orders map by exact demo item name. Catalog-linked unknown items
keep a `square:` ID and need explicit catalog/reference enrollment before vision
checks are enabled. Burritos use label verification rather than guessing fillings.

`OrderSource` in `application/order_source.py` is the replaceable provider boundary.
Square transport and mapping live in `adapters/orders/square.py`. Another POS or a
custom order store can implement the same interface without changing the screens.

## Vision handoff

New tickets return `disposition="pending"`. Manual review uses `needs_review`;
manual fulfillment uses `overridden`, never a fabricated vision pass. Live tickets
without a camera check return `current_check=null`. Tickets never turn green just by arriving from Square.
The kitchen's **Enable camera** button opens a local browser preview; **Check order**
submits a single cropped frame. Automatic checks are opt-in, wait for a changed
scene to settle, and pause on failures or when the tab is hidden. There are no
application spending caps or forced cooldowns. The expandable check-activity
section counts attempts over recent time windows. Square reservations prevent
simultaneous paid checks; failed or uncertain attempts are not automatically
retried. A crashed inference expires as failed after 90 seconds. A successful
inference remains pending until the capturing screen confirms its view stayed
unchanged; this confirmation expires after 15 seconds. A separate two-minute
worker reservation keeps other kitchen screens off the same unfinished ticket.
Full compact observations, including every unexpected item, are shared through
station snapshots. See the README for motion-check limitations.
Neither camera images nor API keys are stored in Square metadata. The backend
resizes images, loads saved references only for this ticket, and calls Perceptron
once. New item edits or manual decisions invalidate outstanding checks through
Square revision checks. The menu editor requests camera
permission only when **Take photo** is clicked, and stops its camera when captured,
closed, or navigated away from. It does not call the vision API.

## Verification

`python -m pytest -q tests/test_square_orders.py tests/test_menu_sync.py` covers request validation,
server-owned prices, idempotency forwarding, independent API instances, pagination,
location isolation, provider failures, the soft ten-ticket cap and concurrent status/cleanup changes, shared menu editing,
demo authorization, conflicting edits, photo validation/replacement, upload retries,
catalog archiving, safe checkout retries, and manual status persistence. Frontend
tests cover queue colors, automatic advance, stale polls, retries, and menu visibility. Run it in the
workspace virtual environment. `npm --prefix apps/web run build` checks TypeScript
and builds both pages. Live Sandbox testing should use an explicitly identified
test basket and verify that it appears in the other browser's queue.
