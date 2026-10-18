# FullFill demo video — internal outline

**Target:** 2:45, with room to edit between 2:30 and 3:00. Talking points, not a word-for-word script.

**Story:** catch a missing item → fix it → show one-photo setup → explain how this makes order verification more accessible → handle uncertainty.

## Run of show

| Time | Show | Key point |
| --- | --- | --- |
| 0:00–0:12 | Customer opens a takeout order; ticket includes a drink, but no drink arrived. | Catch mistakes before pickup. |
| 0:12–0:24 | Brief team introduction, logo, camera setup. | FullFill checks takeout orders using a camera and menu photos. |
| 0:24–0:43 | Place an order; show the same ticket appearing in the kitchen queue. | Working Square Sandbox integration. |
| 0:43–1:10 | Lay out the order without the drink; show the completed camera check naming the missing item. | Specific, actionable feedback. A red queue card alone isn't the detection result. |
| 1:10–1:28 | Add the drink; show a fresh green result labeled **Camera match**. | Correction verified on the same ticket. |
| 1:28–1:50 | Save one labeled reference photo for a menu item; show the camera/browser setup. | No restaurant-specific model fine-tuning or large training dataset. Less setup and ordinary hardware: a path to lower adoption costs for independent restaurants. |
| 1:50–2:09 | Simple architecture diagram; highlight the POS connection. | Browser photo + references → backend/Perceptron → comparison rules → Square. Square Sandbox works now; other POS systems can be connected through adapters. |
| 2:09–2:33 | Second complete order with an unreadable burrito label; show amber and staff review. | Hidden fillings need readable labels or a person. Manual green says **Confirmed by staff**. |
| 2:33–2:45 | Complete order handed off; logo/team closing shot. | Make order verification accessible to independent restaurants, beyond large chains. Next: test in a working kitchen. “Catch the mistake before the order leaves.” |

## Main pitch — setup scene

“Give FullFill one labeled reference photo per menu item—no restaurant-specific model fine-tuning. A camera, a browser, and our POS integration bring the workflow together. Our goal is quicker setup and lower adoption costs, making order verification accessible to more restaurants.”

**Framing:** Perceptron is already pretrained; the photo is a reference, not new training. Emphasize setup/accessibility. Cheaper licensing, faster inference, and compatibility with every POS need separate evidence; commercial pricing varies and open-source alternatives exist.

## Prep and recording

- Props: labeled burrito, fries, drink, readable ticket, camera mount. Save reference photos for every demo item.
- Rehearse missing-drink, corrected-order, and unreadable-label cases. Use the real ordering/kitchen pages and genuine camera results.
- Keep the same ticket through the main demo. Clear the packing area before the second order; keep all its items present for the uncertainty case.
- Keep result text readable. Label shortened waits; hide credentials. Don't claim unmeasured speed/accuracy or unfinished Photon features.

## Timing options

- **2:30:** trim 5 seconds each from team intro, ordering, and architecture; keep the one-photo/accessibility pitch.
- **3:00:** add 15 seconds showing a new item photographed, saved, ordered, and checked—only if rehearsed and readable. Condense setup openly.

## References

- [Pitch, customer interview, and judge questions](../order-checker.md)
- [Current features and limits](../README.md)
- [Square and camera workflow](square-demo.md)
