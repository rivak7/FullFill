# FullFill demo video — talking points and actions

**Target:** 2:45; final cut between 2:30 and 3:00.

Use this alongside the [short storyboard](demo-video-storyboard.md). These are
cues for speaking naturally, not paragraphs to memorize. Pick the main points
for each scene; let the footage carry the actions. Aim for roughly 280–320 spoken
words across the video, leaving room to see the results.

**Main takeaway:** FullFill catches visible order mistakes before pickup, using
one labeled reference photo per menu item without restaurant-specific model
fine-tuning. The goal is to make this workflow accessible to smaller restaurants.

## 1. The problem — 0:00–0:12

**Talking points**

- A missing drink is a small packing mistake that becomes the customer's problem
  once the order leaves.
- The useful time to catch it is at the restaurant, before pickup.

**Actions / footage**

- Briefly show a worker handing off a bag, then the customer unpacking it.
- Put the ticket beside the food: **1 chicken burrito, 1 fries, 1 drink**. Show
  the drink line and the missing drink clearly.

**Lead-in:** “What if we caught that before the order left?”

## 2. Introduce FullFill — 0:12–0:24

**Talking points**

- Introduce Roy, William, and Rishabh briefly, with names on screen.
- FullFill checks takeout orders using a camera, the digital ticket, and the
  restaurant's menu photos.

**Actions / footage**

- One short team shot, then immediately show the camera and kitchen screen.
- Establish the physical setup: an ordinary camera over the packing area, with
  a browser showing the order. No long logo animation.

**Lead-in:** “Here's the whole flow, starting with an order.”

## 3. Order entry and kitchen integration — 0:24–0:43

**Talking points**

- An order placed on the customer page appears in the kitchen queue.
- The ticket and quantities are shared through the actual Square Sandbox
  integration. This is a connected workflow, not just an isolated photo demo.

**Actions / footage**

- Order the burrito, fries, and drink on the customer page.
- Show the matching ticket ID on the kitchen page and select it.
- Keep a small **Square Sandbox demo** caption visible.

**Lead-in:** “Now let's pack it, but leave something out.”

## 4. Catch the missing item — 0:43–1:10

**Talking points**

- The worker lays out the order; the drink is missing.
- When the scene settles, FullFill checks a camera frame against the ticket and
  saved menu references.
- The result names the discrepancy, giving the worker something specific to fix.

**Actions / footage**

- Put the labeled burrito and fries in view. Keep the drink off the packing area.
- Show the physical order, selected ticket, and camera preview together.
- Capture **Checking…**, then the completed mismatch result and missing-drink
  message. Hold the message long enough to read.

**Important:** a new ticket already appears red. The proof is the completed
camera check naming the missing item, not the queue card's color alone.

## 5. Fix it and recheck — 1:10–1:28

**Talking points**

- The worker adds the missing drink and the changed scene gets a fresh check.
- The green result is a **Camera match** on the corrected order.

**Actions / footage**

- Add the drink without changing tickets; show the fresh check and green result.
- If the queue advances, select the completed ticket again to show its result.
- Finish bagging the corrected order.

**Lead-in:** “The restaurant sets this up with photos of its own menu.”

## 6. One-photo setup and accessibility — 1:28–1:50

**Talking points — prioritize this section**

- One labeled reference photo per menu item; no restaurant-specific model
  fine-tuning or large training dataset to collect.
- Perceptron is already pretrained. We supply the item's name and photo as
  reference context; adding a menu item does not retrain the model.
- Ordinary camera/browser hardware and a simpler setup are the route to lower
  adoption barriers for independent restaurants.

**Actions / footage**

- Show a real menu item being named and photographed or its photo uploaded.
- Save it, then show its saved photo beside the physical item.
- Useful captions: **One reference photo per item**, **No fine-tuning**.

**Anchor phrase:** “The goal is quicker setup and lower adoption costs, making
order verification accessible to more restaurants.”

Keep this about setup and access. One reference photo is the setup input, not a
guarantee of recognizing every item under every condition. Lower licensing costs
and faster inference than competitors are not measured claims in this demo.

If briefly contrasting alternatives, substitute this point for another line:
manual checks rely on attention; scales measure total weight; FullFill names
item-level discrepancies. Do not add a lengthy competitor section.

## 7. How it works and where POS fits — 1:50–2:09

**Talking points**

- The browser captures a frame; the backend sends it and relevant menu photos
  to Perceptron.
- Perceptron reports observed items and counts without being told the expected
  quantities. Separate application rules compare those observations with the ticket.
- Square shares the orders and results. Other POS systems would need their own
  adapters; Square Sandbox is the integration being demonstrated today.

**Actions / footage**

- Use one simple diagram: **Photo + references → Perceptron → comparison rules
  → kitchen result**, with **Square ↔ orders/results** alongside it.
- Highlight the steps while keeping the working product visible. Skip code and
  scrolling repository pages.

**Lead-in:** “And when the photo can't tell us enough, we ask a person.”

## 8. Uncertainty and human review — 2:09–2:33

**Talking points**

- A closed wrapper cannot prove the filling inside. An unreadable required label
  should lead to review, not a confident guess.
- Staff can inspect and confirm an order. That is identified separately from a
  camera match.
- Scope: visible items and readable labels; hidden ingredients and special
  instructions still need human judgment.

**Actions / footage**

- Use a second ticket. Clear the area between orders and select the correct ticket.
- Include every item, but hide the burrito's required label. Show the actual amber
  result and its reason. Keep the other items present so a shortage does not dominate.
- Have a worker inspect and confirm it. If showing green afterward, hold the
  **Confirmed by staff** detail.

## 9. Close on the benefit — 2:33–2:45

**Talking points**

- The ambition: make order verification accessible to independent restaurants,
  beyond large chains, with less restaurant-specific setup.
- Next step: test the workflow in a working kitchen. This is a proposed next
  step, not an already secured pilot.

**Actions / footage**

- Hand off the complete order, echoing the opening shot.
- End on the team or logo and **Catch the mistake before the order leaves.**

## Delivery and recording notes

- Keep one main narrator through the order/demo; use a speaker change at setup
  or architecture if everyone needs a speaking part. Record explanations over
  footage so the video keeps moving.
- Rehearse the three real results: missing item, corrected order, uncertain label.
  Use the real ordering/kitchen pages, not static `/demo` states.
- Prepare saved reference photos and a readable burrito label matching its
  configured name/aliases. Keep the camera angle and lighting consistent.
- Keep the same ticket through the missing-item/correction sequence. A camera
  result describes that photo, not continuous proof of the bag's contents.
- If shortening a model wait, label it **Waiting shortened**. Do not treat edited
  timing as a speed measurement. Keep access codes and credentials out of frame.
- Treat lower costs and broader access as the goal; do not say every alternative
  is proprietary, every POS is supported, or Photon alerts are implemented.

## Adjusting the length

- **2:30:** trim five seconds each from the intro, order entry, and architecture.
  Keep the one-photo/accessibility explanation and readable result shots.
- **3:00:** add a rehearsed 15-second new-item sequence after setup: photograph,
  save, order, and genuinely check an unfamiliar item. Label condensed setup and
  shortened waiting. Omit it if the result cannot be shown clearly.

## Five Golden Questions coverage

| Question | Where we answer it |
| --- | --- |
| Problem | Opening missing-item scene. |
| Current approaches | During setup: manual attention and weight checks versus item-level photo verification; keep comparisons brief. |
| Our solution | Introduction and the complete missing-item/correction demo. |
| Why this approach | One-photo references, no fine-tuning, accessible hardware, and connected workflow. |
| Implementation / next step | Architecture and Square integration; working-kitchen validation in the close. |

References: [Five Golden Questions](../order-checker.md#1-pitch-the-five-golden-questions),
[current behavior and limits](../README.md), [Square/camera workflow](square-demo.md).
