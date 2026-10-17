# Station screen

What the worker sees next to the mat: the ticket on the left, one big color on the right.

| Color | When | Worker does |
| --- | --- | --- |
| Green "Order fulfilled" | Every ticket item was seen | Bag it |
| Red "Order unfulfilled" | Something is missing or extra | Fix what the list says, the camera rechecks |
| Amber "Needs a quick look" | The camera isn't sure (e.g. a burrito with no C/S label) | Look and use their judgment; clearing the mat ends the order |
| Grey "Checking…" / "Lay out the order" | Check running, or no check yet | Wait |
| Dark "Couldn't check this order" | The check failed | Check by hand; never counts as green |

## Files

- `screenState.ts` decides the color, headline, and per-line marks from an `OrderState`. Change the rules here and only here.
- `StationScreen.tsx` draws it. Takes `state`, nothing else. It is display only: the worker never taps it.
- `station.css` is all the styling. Colors are the variables at the top.
- `fakeOrders.ts` holds the hardcoded scenarios used by the demo bar at the bottom of the page.

## Running

```
cd apps/web
npm install
npm run dev
```

Click the buttons at the bottom to switch scenarios.

## Hooking up the real backend

`OrderState` comes from `src/api/generated/contracts.ts` (generated from `packages/contracts`), so it is the same shape the API sends.
In `App.tsx`, replace the fake `state` with the order from `StationApi.getStation` / `subscribe` and delete the demo bar.
