# FullFill

FullFill checks takeout orders before they're bagged. A phone camera looks down at the packing mat, and when an order is laid out, FullFill compares what it sees with the ticket and tells the worker right away if something is missing or wrong.

Built at DubHacks 2026.

## What it does

1. A customer orders, and the cashier rings it up as usual. The order shows up on the kitchen screen next to a live view of the packing mat.
2. The worker sets the order's items out on the mat, like they would before bagging anyway.
3. Once the mat stops moving, FullFill takes a photo and counts what's there. A few seconds later, the screen turns one of three colours:
   - **Green:** everything on the ticket is there.
   - **Red:** something's off, and it says exactly what ("Missing: 1 Ketchup", "Wrong item: Veggie Burrito").
   - **Amber:** it isn't sure (say, two burritos look identical and it can't read the label), so it says why in one line and leaves the call to the worker.
4. The worker bags the order. A green order moves on by itself, and so does a red one the worker decides to bag anyway. An amber order waits until the worker moves on.

The worker never has to scan, tap or confirm anything during a normal order. The camera only points at the mat, never at people, and photos aren't saved.

To set up a restaurant, you add a photo of each menu item. That's it: no training. FullFill shows the AI those photos next to the photo of the order, so it can tell apart this kitchen's own containers and sauces, including two dishes that look almost the same.

## Try it

| Site | What it's for |
| --- | --- |
| [Order site](https://fullfill-order.vercel.app) | Place an order, like a cashier or customer would. |
| [Kitchen screen](https://fullfill-kitchen.vercel.app) | The order queue, the camera check, and the **Menu** tab for adding items and their photos. |

Both ask for the team's demo access code.

## How it works

Orders go through [Square](https://squareup.com), a point-of-sale (POS) system, so FullFill reads them the same way it would in a real restaurant. The kitchen screen (a KDS, or kitchen display system) runs in the browser and watches a tiny copy of the camera feed to notice when the mat settles. Only then does it send one photo to our server. The server asks [Perceptron](https://www.perceptron.inc)'s vision model to count each item, without telling it what was ordered, and our own rules turn those counts into green, red or amber.

More detail: [technical notes](docs/technical-notes.md).

## Running it yourself

You'll need Python 3.13, [uv](https://docs.astral.sh/uv/), Node 22.12+, a Square Sandbox account, and a Perceptron API key for camera checks.

```sh
uv sync --locked --inexact
npm --prefix apps/web ci
cp .env.example .env   # add your Square Sandbox token and location ID, and PERCEPTRON_API_KEY
uv run python scripts/seed_square_menu.py
```

Then start the API and the web app in two terminals:

```sh
uv run --no-sync uvicorn fullfill.main:create_app --factory --reload --env-file .env --host 127.0.0.1 --port 8000
npm --prefix apps/web run dev
```

Open `http://127.0.0.1:5173/order` to place an order and `http://127.0.0.1:5173/fulfill` for the kitchen screen. The [developer guide](docs/developer-guide.md) covers configuration, hosting, the API and tests.

## License

[MIT](LICENSE)
