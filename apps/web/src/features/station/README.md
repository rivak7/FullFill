# Station screen

What the worker sees next to the mat: the ticket on the left, one big color on the right.

| Color | When | Worker does |
| --- | --- | --- |
| Green "Order fulfilled" | Every ticket item was seen | Bag it |
| Red "Order unfulfilled" | Something is missing or extra, or a menu item that isn't on the ticket | Fix what the list says, the camera rechecks |
| Amber "Needs a quick look" | The camera isn't sure (e.g. a burrito with no C/S label, an object it can't identify, or a poor view) | Look and use their judgment; clearing the mat ends the order |
| Grey "Checking…" / "Lay out the order" | Check running, or no check yet | Wait |
| Dark "Couldn't check this order" | The check failed | Check by hand; never counts as green |

## Files

- `screenState.ts` decides the color, headline, and per-line marks from an `OrderState`. Change the rules here and only here.
- `StationScreen.tsx` draws it. Takes `state`, nothing else. It is display only: the worker never taps it.
- `station.css` is all the styling. Colors are the variables at the top.

The kitchen screen (`../orders/FulfillmentScreen.tsx`) feeds it live orders from the API.
