# Square order entry and fulfillment

The order entry screen creates orders in Square Sandbox. The fulfillment screen
polls that same location every three seconds. Square holds the orders; they are
not stored in a browser or an API process's memory. The current integration does
not charge payments, run camera checks, or mark orders fulfilled.

## Run locally

1. Install the workspace with `make setup` (Python 3.13 and Node 22.12+).
2. Set `SQUARE_ENVIRONMENT=sandbox`, `SQUARE_ACCESS_TOKEN`, and
   `SQUARE_LOCATION_ID` in the root `.env`. `SQUARE_APPLICATION_ID` may stay there
   for future integrations; these server-side order calls don't require it.
3. Set `FULLFILL_MENU_KEY` to a separate random code of at least 32 characters.
   Run `uv run python scripts/seed_square_menu.py` once to add missing starter items
   to Square Catalog. This preserves any existing edits, including archived items.
4. Run `make dev-api`. It reads `.env`; restart it after changing credentials.
5. In another terminal run `make dev-web`.
6. Open `http://127.0.0.1:5173/order` and `http://127.0.0.1:5173/fulfill`.
7. Place an order. It joins the fulfillment queue automatically. Select its
   ticket to see the item quantities. New arrivals never replace a selected ticket.

The original screen-state examples are available separately at `/demo`.
The `/` route opens the live fulfillment queue.

## Edit the shared menu

Open **Menu** on the kitchen site and enter the menu editing code. Staff can add
items, change names and prices, mark items sold out, and archive or restore items.
The ordering screen refreshes every five seconds and when returning to the tab.
If a selected item changes, checkout pauses until the customer reviews the basket.
Unavailable items must be removed before placing a new order.

Menu data persists in Square Sandbox Catalog across computers and deployments.
Only FullFill-managed catalog items at the configured location are editable here.
Each variation's `user_data` holds the stable FullFill item ID, location, availability,
and verification mode. Version checks reject conflicting simultaneous edits.
New items still need vision reference enrollment; adding a menu item does not train
the vision checker. Existing burritos retain label verification.

The active kitchen queue shows the newest **30** nonempty open orders. When order
31 arrives, the oldest drops out of every kitchen screen on the next refresh.
The kitchen refresh archives overflow tickets using Square order metadata, so
they stay out after reloads or after newer orders finish. The original Square order
remains retrievable by ID; its payment and fulfillment state are unchanged.

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

The hosted demo protects API reads and writes with `FULLFILL_ACCESS_KEY` and HTTPS.
Each browser asks for that shared demo code. CORS restricts browser origins but
is not authentication. The local servers do not need to be exposed publicly.

## API and integration boundary

| Route | Behavior |
| --- | --- |
| `GET /v1/menu/current` | Returns the shared catalog menu and its revision |
| `GET /v1/menu/manage` | Reads the menu with staff authorization |
| `POST /v1/menu/items` | Saves an item; requires `X-Menu-Key` and `Idempotency-Key` |
| `POST /v1/orders/prepare` | Validates the menu revision and returns a signed checkout |
| `POST /v1/orders` | Creates an order from that checkout with the same `Idempotency-Key` |
| `GET /v1/orders` | Lists the newest 30 open, nonempty orders at the configured location |
| `GET /v1/orders/{id}` | Retrieves the shared `OrderSnapshot` for a vision consumer |
| `GET /v1/stations/main` | Returns those orders as a `StationSnapshot` |
| `POST /v1/stations/main/refresh` | Archives queue overflow and returns the latest station snapshot |

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

The adapter follows queue pages until it has 30 eligible tickets, with a bounded
2,000-record scan if most records are empty or otherwise ineligible.
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

All live tickets currently return `disposition="pending"` and `current_check=null`.
They must not turn green merely because they arrived from Square. The vision
workflow can fetch `OrderSnapshot` by ID and later supply its actual `CheckResult`
through the station snapshot. Associate results with the order ID and revision;
do not reuse a result after the order changes. No camera permission or vision API
call is triggered by these pages.

## Verification

`python -m pytest -q tests/test_square_orders.py tests/test_menu_sync.py` covers request validation,
server-owned prices, idempotency forwarding, independent API instances, pagination,
location isolation, provider failures, the 30-ticket cap, shared menu editing,
staff authorization, conflicting edits, safe checkout retries, and pending check state. Run it in the
workspace virtual environment. `npm --prefix apps/web run build` checks TypeScript
and builds both pages. Live Sandbox testing should use an explicitly identified
test basket and verify that it appears in the other browser's queue.
