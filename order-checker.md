# Order Checker: Project Plan (DubHacks '26)

*Last updated Saturday, October 17, 2026. This file replaces `idea-order-checker.md` and `order-checker-feasibility.md`. Everything still useful from both is merged in here, along with what we learned since: the Atoms talk Q&A, the interview with the Dub Street Burgers cook, Perceptron's credits, the design review, the comparison with Intel's open-source order checker, and what we learned at Perceptron's workshop. The tech stack and task checklist are right below the summary.*

## Summary

A phone mounted over a mat at a restaurant's packing station checks each order before it leaves. The worker sets the order's items and the printed ticket on the mat. The phone takes one photo once the mat is still, and Perceptron compares it against reference photos of just the items on that ticket. While the worker bags, the screen turns green, or turns red and names what's missing ("Missing: ranch cup"). The manager gets a text through Photon when an error is caught.

Restaurants set it up by photographing each menu item a few times. **Nothing is trained.** Companies like Atoms build this with models fine-tuned on large amounts of data for big chains. Intel's open-source Dine-In app shows a pre-trained model can check orders without fine-tuning, but it matches on item names only and needs a GPU server to run. **Our claim:** photos of the restaurant's own items make checking work on its lookalike items and packaging, with no training and no hardware beyond a phone, set up by the owner in minutes.

---

## Tech stack

All of it runs on one MacBook plus the cloud. No GPU, no Arduino, no custom hardware.

**Hardware**
- **iPhone as the station camera.** Connected to the Mac **by cable** through Apple's Continuity Camera (USB-C to USB-C for iPhone 15 or newer, USB-C to Lightning for older). Tap "Trust" on first connect. The wired connection is more stable and keeps the phone charged. **The camera phone can't also share its hotspot** (Continuity Camera refuses while the iPhone shares its cellular connection), so the hotspot comes from a teammate's phone.
- **MacBook:** runs the capture code, the backend, and the station screen.
- **Mat:** a plain, matte, solid color that contrasts with the containers (flattened cardboard, a dark hoodie, or dark poster board), edges taped.
- **Mount:** two chairs back to back with a broom handle or yardstick across the top, phone taped in the middle facing down. Within cable reach of the Mac, and never moved between tests and the demo.
- **Network:** a teammate's phone hotspot as the main connection; Ethernet through a USB-C adapter or venue Wi-Fi as backup.

**Capture layer (Python + OpenCV, on the Mac)**
- Reads the iPhone feed as an ordinary camera index (try 0, 1, 2; grant Terminal or VS Code camera access the first time).
- Stillness trigger: frame differencing inside the mat area fires once the scene has been still for about 0.5 s. Manual "Check" button as fallback.
- Decodes the ticket's QR code locally (OpenCV's QR detector) to get the order ID from the same photo.
- Crops to the mat and downscales to about 1024 px before upload.

**Backend (Python, FastAPI)**
- Mock order queue, menu, and **reference library** (photos taken through the station camera).
- **Perceptron request layer:** Mk1.5, Text output with a JSON schema, reference photos only for items on the current ticket, reasoning off, a small output limit. A follow-up call in **Point** mode only for flagged items. **Cooldown between calls and a hard cap on total calls.** API key in an untracked `.env`.
- Per-order state (in progress, green, amber, red, resolved), with red flags persisting until resolved.
- Pushes updates to the station screen over a WebSocket, and logs every check for evaluation.

**Perceptron (cloud):** Mk1.5. Prompts are prototyped in the playground at perceptron.inc/demo, then copied with its **Export** button into the request code.

**Frontend (React, William)**
- Station screen: live feed, the current order as a checklist, green, amber, and red states, and the order queue.
- Setup screen: capture reference photos through the station camera, and add new items (the live "judge adds an item" moment).

**Photon (Spectrum, TypeScript):** a small service that texts the manager on caught errors and overrides, sends shift summaries, and accepts new menu items by text. Optional; the core project works without it.

**Evaluation (Python, Rishabh):** T1–T3 tests, held-out item accuracy, names-only vs. names-plus-photos, the untrained-detector baseline, and cost per check.

**How it fits together:** the worker sets out the order and the ticket → the capture layer sees the mat go still, reads the QR code, and crops the photo → the backend sends the photo plus that ticket's reference photos to Perceptron → the JSON checklist comes back and is compared with the order → the station screen turns green, amber, or red, and Photon texts the manager on errors.

---

## Task checklist

*As of about 2 PM Saturday. Owner in brackets.*

**Done**
- [x] Check in
- [x] Redeem Perceptron credits and create an API key [Rishabh]
- [x] Confirm the model (Mk1.5) and that credits are $50 per person
- [x] Perceptron workshop: speed, rate limit, number of reference photos

**Setup**
- [ ] Roy and William redeem their credits and create backup keys [Roy, William]
- [ ] Put one key in a shared, untracked `.env` [Roy]
- [ ] Photon account and a hello-world text; confirm which Mac handles iMessage [Roy]
- [ ] Get a USB cable for the camera phone, and decide whose phone is the hotspot [William]

**Props** (University Book Store closes at 6 PM today)
- [ ] Mat: flattened cardboard, a dark hoodie, or dark poster board
- [ ] Mount: chairs and a broom handle or yardstick, or a tripod from the organizers' hardware desk or Target
- [ ] Painter's tape and a thick marker
- [ ] Empty clamshells, lidded sauce cups, and to-go bags (Ave restaurants, the Dub Street cook)
- [ ] Lookalikes and fillers from Safeway (open until 1 AM): portion cups, ketchup, ranch, Coke and Diet Coke
- [ ] Snacks and cans from the event table
- [ ] Tickets with QR codes printed, or shown on a second phone

**Testing** (go/no-go by about 3 PM)
- [ ] In the playground, run the kit demo and time Text, Point, and Box output [Rishabh]
- [ ] **Pick the mount angle first**, then take reference photos through the station camera [William]
- [ ] T1 latency, T2 accuracy, T3 lookalikes and labels [Rishabh]
- [ ] Go/no-go call [team]
- [ ] Take a real failure example to Perceptron at HUB 307 [anyone]

**Build**
- [ ] Capture, stillness trigger, QR decoding, crop and downscale [William]
- [ ] Mock order queue and tickets [Roy]
- [ ] Perceptron request layer with JSON schema, cooldown, and call cap [Roy]
- [ ] Station screen with green, amber, and red states and persistent red flags [William]
- [ ] Setup screen for reference photos and adding items [William]
- [ ] Photon manager texts and shift summary [Roy]
- [ ] Thresholds for `unsure` [Rishabh]

**Evaluation**
- [ ] Split items into tuning and held-out sets, and report held-out accuracy [Rishabh]
- [ ] Names only vs. names plus photos [Rishabh]
- [ ] Untrained-detector baseline [Rishabh]
- [ ] Cost per check and ROI numbers [Rishabh]

**Validation**
- [ ] Ave restaurant chats, 2–4 PM, at least one quote [one person]

**Demo and submission**
- [ ] Rehearse the 60-second loop and the live "judge adds an item" moment
- [ ] Record the backup demo video once the full loop works
- [ ] Devpost write-up, tracks selected, video attached
- [ ] Submit before 10 AM Sunday

---

## 1. Pitch: the five golden questions

**1. What's the problem?**
At small restaurants doing delivery, the person packing bags during a rush can't reliably check every item against the ticket. Missing or wrong items reach customers who can't check until they're home.
- The Atoms speaker estimated **4–6% of online delivery orders** are missing an item or have a wrong one. This is his rough figure ("I think something like"), and we couldn't verify it independently. Present it that way.
- Drive-thru orders across 13 brands averaged **87% accuracy** in a 2025 study.
- In a 2022 survey, **63% of consumers** had received at least one incorrect delivery order, 24% asked for a refund, and 20% wouldn't order from that restaurant again.
- Who and when, from the cook we interviewed: mistakes happen when it's slammed, with about 200 customers and only three people in the kitchen.

**2. What are the current solutions?**
- **People checking tickets by eye**, which is exactly what fails during a rush.
- **Scales** (DoorDash SmartScale, ACRELEC Double-Check). They can tell an order is too light, but not which item is missing, and a light item like a sauce cup gets lost in normal portion variation.
- **Custom-trained camera systems** (Atoms' Verify, Agot AI, PreciTaste). They work, but each is trained on large amounts of data for a specific chain, so they're built for big enterprise customers.
- **Intel's open-source Order Accuracy app.** Its Dine-In version uses a pre-trained vision-language model with no fine-tuning, but it matches detected items to the order by name only, and it's a GPU-and-Docker setup built for integrators, not owners.

**3. What's our solution?**
The phone-over-a-mat checker described in the summary.

**4. How is it better?**
- **It checks against photos of the restaurant's own items, not just names.** A name like "ranch cup" can't tell ranch from aioli or describe a specific clamshell; a reference photo can. Our names-only vs. names-plus-photos comparison is the proof (section 7).
- **No training.** Setup takes minutes instead of collecting and labeling data. That's the gap raised at the Atoms talk (section 2). Credit Intel's project as evidence that pre-trained models can check orders at all; don't claim we're the first to skip training.
- **It names the missing item**, including light items a scale misses.
- **No special hardware:** a phone, a mat, and an internet connection, instead of a GPU server.
- **It acts, not just detects:** a red flag that stays up until resolved, manager texts, shift summaries, and adding items by text.
- **It's cheap:** about $0.003 per check at Perceptron's listed prices.
- **Speed, only if T1 passes:** Intel lists 9–15 s end to end. If our median is under 4 s, say so; don't claim it before measuring.

On "what's proprietary," be honest: not much yet. Over time the advantage would be each restaurant's library of reference photos and its record of which errors happen. Don't overclaim it.

**5. How do you implement it?**
- **This weekend:** run the speed and accuracy tests by 3 PM Saturday, then build the loop, the station screen, and the manager texts (roles in section 10).
- **After the hackathon:** a free one-week pilot at a restaurant on the Ave, then connecting to the restaurant's order system so tickets arrive automatically, and encouraging lid labels so it can check entrées inside closed containers.

**Say our limits up front:** we only check what's visible or labeled, never what's inside a closed container or modifiers like "no onion."

---

## 2. Where the idea came from

### The Atoms talk
A talk at UW a few days before the hackathon by Atoms (the company behind Picnic, Lab 37, Otter, and Seattle kitchen sites like District Eats). **Atoms is not a DubHacks sponsor**, so building in their space carries no conflict. Credit the talk as our inspiration. The recording was transcribed automatically (`atoms-talk-transcript.md`); the talk is clean, but the Q&A after about 13:30 is badly garbled.

- They're building a product called **Verify** (name from the automatic transcript). A Raspberry Pi with a camera and a small screen sits over the packing table. It reads the receipt, checks the items laid out on the table, and prompts the worker to fix mistakes. In their demo it catches a Sprite that should have been a Coke. It uses **their own trained models** with about 100 ms response time.
- In the Q&A, someone asked why a restaurant shouldn't just use YOLO instead of buying from Atoms. **The answer was that they had to fine-tune on a lot of data.** That's the gap we're building into: no fine-tuning, usable by small restaurants.

### The cook interview
We talked to a cook at Dub Street Burgers in Local Point (UW dining).
- Orders are mostly made right. Mistakes happen when it's very busy, around 200 people with 3 people in the kitchen. Customers sometimes pick up the wrong order or get impatient, and things get mixed up.
- Customers often don't point out mistakes. He'd rather they did, because he's happy to fix them.
- When orders truly go wrong, it's often because ingredients ran out. He tells his manager when stock is low, but when they're short-staffed that message often doesn't get through.
- Dubgrub (UW's online takeout) rarely has fulfillment problems.
- He thinks other restaurants are similar.
- **He said a camera over his workstation would probably slow him down.**

### What we changed because of the interview
- **Target restaurants doing delivery, not dining halls.** At a dining hall the customer stands at the counter and can catch a mistake. In delivery, nobody checks the bag until it's too late. That also explains why he sees few problems and Atoms sees many.
- **Take the "slows me down" objection seriously.** The design asks for no buttons and no extra steps beyond laying the order out, which many kitchens already do. Confirm this with Ave restaurants (section 13).
- **Dropped:** an ingredient-level tracker. PreciTaste already sells camera-based fill-level monitoring, and since orders are already digital, the system knows how much of each item goes out without a camera.

---

## 3. Research

### How common errors are
- **4–6%** of delivery orders missing an item or wrong (Atoms speaker's estimate, unverified).
- **87%** average drive-thru accuracy across 13 brands. 51% of mistakes were missed ice requests and 25% were wrong items ([Intouch Insight, 2025](https://intouchinsight.com/blog/drive-thru-trends)).
- **63%** of consumers received at least one incorrect delivery order. 24% asked for a refund, and 20% wouldn't order from that restaurant again ([eduMe via Restaurant Dive, 2022](https://www.restaurantdive.com/news/study-diners-are-dependent-on-food-delivery-but-are-sensitive-to-order-inaccuracies/623372/)).

### Existing products
| Who | Approach | Takeaway for us |
| --- | --- | --- |
| **Atoms Verify** (from the talk; no public documentation found) | Raspberry Pi camera over the packing table; items sit **on the table** while the ticket is checked. Custom models, about 100 ms. | Even they check items laid out on a table, not mid-drop into a bag. |
| **Agot AI** ([CNBC](https://www.cnbc.com/amp/2021/09/16/this-start-up-uses-computer-vision-to-get-your-fast-food-order-made-accurately-.html), [TechCrunch](https://techcrunch.com/2022/02/11/agot-ai-gives-restaurants-computer-vision-to-see-where-food-orders-go-wrong), [Hospitality Tech](https://hospitalitytech.com/agot-ai-raises-12-million-develop-build-computer-vision-tech-foodservice)) | Overhead cameras on the **make line**, trained per restaurant. Claims it spots more than 85% of order errors. Raised $12M; piloted with Yum! Brands. Typical customer has 2,000+ locations. Criticized as using cameras to [spy on employees](https://thetakeout.com/startup-wrong-food-drive-thru-order-1847695904). | Catching errors inside the food has to happen before lids go on, a separate and harder product. Point our camera at the food, never the workers. |
| **PreciTaste** ([Intel brief](https://builders.intel.com/docs/networkbuilders/precitaste-station-assistant-1736257450.pdf), [Chipotle test](https://www.deeplearning.ai/the-batch/chipotle-tests-ai-for-predicting-customer-demand)) | Depth sensors and cameras measure ingredient fill levels and tell crews what to refill; tested at Chipotle, including bag checks. Trained on 500M+ images. | Ingredient tracking is taken. Their setup needs installers and special sensors; ours needs a phone. |
| **Intel's open-source Order Accuracy** ([repo](https://github.com/intel-retail/order-accuracy), [Dine-In how it works](https://github.com/intel-retail/order-accuracy/blob/main/docs/user-guide/dine-in/how-it-works.md)) | **Dine-In** is the closest thing to our design: staff place a tray at a station and trigger a check; a pre-trained Qwen2.5-VL model, **with no fine-tuning**, lists the items using a prompt that includes the menu's item names; detected items are then matched to the order by fuzzy text matching (70% similarity threshold). About 9–15 s end to end. Runs as several Docker containers with a GPU model server; preparing the model needs up to 40 GB of RAM. Describes itself as a sensor that never takes actions. **Take-Away** watches video streams, uses YOLO to pick frames, then the same model. Their docs don't mention reference photos or reading lid labels. | "No training" alone isn't unique. Our differences: matching against photos of the restaurant's own items, phone-only setup for owners, and acting on errors. Reference only, not code (70/30 rule). |
| **DoorDash SmartScale** ([DoorDash](https://about.doordash.com/en-au/news/doordash-launches-smartscale-for-smarter-deliveries), Sept 2025) | A scale compares the order's weight to the expected weight. Cuts missing-item claims by up to 30%; guest-reported missing items fell 42% at Panera. | The biggest player chose weight. Our main competitor. |
| **ACRELEC Double-Check** ([acrelec.com](https://acrelec.com/double-check/)) | Also weight-based. Claims 40% fewer bagging mistakes. | |
| **Weight-check patent** ([US 6115695](https://patents.justia.com/patent/6115695)) | Weight catches a missing item only when portion variation is smaller than the lightest item in the order. | Weight's blind spot is light items like a 30 g sauce cup. A camera handles exactly those. |
| **Toast item labels** ([Toast](https://support.toasttab.com/en/article/How-to-Set-Up-Print-Item-Labels)) | Stickers on each container showing the item, its modifiers, and the guest name. | Kitchens already write what's inside on the outside, so reading labels is how a camera gets past opaque packaging. |

### Perceptron: what we know
- **Models:** **we have Mk1.5** (confirmed at the event). The open-weight Isaac models may be retired from the API.
- **Strengths that matter here:** structured output (points, boxes), reading text, and **in-context learning**: labeled reference photos are sent inside each request, and nothing is trained ([in-context learning docs](https://docs.perceptron.inc/perceptron-mk1.5/capabilities/in-context-learning-image.md)).
- **No streaming or real-time endpoint.** Requests are request/response, with a 120 s limit per call.
- **Rate limit:** 300 requests/minute ([scaling guide](https://docs.perceptron.inc/perceptron-mk1.5/guides/scaling.md)). At the event, Perceptron's team thought this is per API key but wasn't sure. Either way, we'll use far less.
- **Reasoning is off by default**; turning it on adds latency ([reasoning docs](https://docs.perceptron.inc/perceptron-mk1.5/capabilities/thinking.md)).
- **Context window:** about 32–37K tokens. Token cost per image isn't documented, so measure it ([tokenization guide](https://docs.perceptron.inc/perceptron-mk1.5/guides/tokenization.md)).
- **Pricing (Mk1.5):** $0.15 per million input tokens, $1.50 per million output tokens ([quickstart](https://docs.perceptron.inc/perceptron-mk1/index)).

**From Perceptron's workshop (Oct 17):**
- **Inputs:** text, image, video, and audio. **Outputs:** natural language, **formatted output such as JSON schemas or regex**, grounding through points, boxes, and polygons, time-based clips, tracking across video frames, and tool calls (web search, plus focusing and zooming).
- One model handles grounding, counting, multiple detections in one call, and OCR (labels, expiration dates, signs), all through natural-language prompts.
- **In-context learning works with arbitrary objects:** pass an image of what you're looking for when it's hard to describe in words.
- **Reference photos:** **one should work**, and more helps, especially for unusual objects. **References should match the camera's view**: top-down references work much better for a top-down camera.
- **Speed:** their team said a check like ours should take **a few seconds**. Their estimate, so still measure it.
- **Playground output modes:** Text (descriptions), Point (text plus points, good for counting), Box (text plus bounding boxes), Polygon (text plus outlines). **We use Text with a JSON schema for the main check and Point for highlighting flagged items.** Skip Polygon.
- Their playground has an equipment-kit example that compares an approved kit photo with a packed kit and calls out missing and extra items, essentially our design.
- **Where to find them:** HUB 307 (the robot room).

**Published speed numbers disagree badly:**
| Source | Model | Figure |
| --- | --- | --- |
| [Mk1.5 launch post](https://www.perceptron.inc/blog/introducing-perceptron-mk1-5) (vendor, best case) | Mk1.5 vs Mk1 | Image Q&A 0.51 s (Mk1: 1.7 s); a 60-second video takes 9.1 s (Mk1: 19 s) |
| [OpenRouter](https://openrouter.ai/perceptron/perceptron-mk1) | Mk1 | About 0.62 s to first token, 28–30 tokens/s |
| [modelgrep](https://modelgrep.com/best/lowest-latency/perceptron) | Mk1 / Mk1.5 | Mk1: 1.2 s to first token, 10 tokens/s. Mk1.5: 23 s to first token, 7 tokens/s (possibly launch-week load) |
| [thegtmdirectory](https://thegtmdirectory.com/models/perceptron-perceptron-mk1/perceptron-mk1) | Mk1 | Median end-to-end 8.28 s; no source or date |
| [VentureBeat](https://venturebeat.com/technology/perceptron-mk1-shocks-with-highly-performant-video-analysis-ai-model-80-90-cheaper-than-anthropic-openai-and-google) | Mk1 | Processes video at up to 2 frames per second |

**Takeaway:** a one-image check with a short answer probably takes 1–8 s, worst case unknown. **Output length matters most.** At 7–30 tokens/s, asking for boxes on 8 items (about 300 output tokens) could take 10–40 s alone. Keep answers tiny.

---

## 4. Design: set out → snapshot → bag

### Why checking items one by one as they drop into the bag fails
| Assumption | Reality |
| --- | --- |
| Check each item as it goes in | Video is sampled at a few frames per second with no streaming endpoint. One second of a hand carrying an item gives 1–2 blurry, half-covered frames. |
| The check is near-instant | Realistically 1–8 s per call; independent measurements reach 20+ s. |
| The camera can see what's in the bag | Once an item is in an opaque bag, it's gone. Every check has to happen before bagging. |
| The camera can identify food | Food in identical closed clamshells looks identical. Modifiers are invisible. |

A real-time version would need a local custom-trained detector, which loses the no-training pitch and makes Perceptron no longer the core of the project.

**The key insight:** the real deadline is the courier picking up the bag, not the moment an item drops in. A verdict a few seconds later is still in time.

### How it works
1. **The order is known digitally.** In a real kitchen, orders come from the order system or a delivery tablet. For the demo, we build a mock order queue and print tickets with a large order number and a QR code.
2. **The worker sets the order's items and the ticket on the mat**, items spread out, never stacked. One order on the mat at a time.
3. **Automatic trigger:** a cheap local motion check (OpenCV frame differencing) fires once hands leave the mat and the scene stays still for about 0.5 s, which also guarantees a sharp frame. An on-screen "Check" button is the fallback.
4. **The order ID comes from the same photo.** OpenCV decodes the ticket's QR code locally, instantly, with no extra step and no extra API call. We don't read the ticket text with the model; it adds delay and a way to fail.
5. **One Perceptron call:**
   - the snapshot, downscaled to about 1024 px
   - reference photos **only for the items on this ticket** (usually 2–6), so we stay well inside the context window
   - **Text output with a JSON schema:** one entry per ticket item, each `present`, `missing`, or `unsure`, plus any unexpected items
   - reasoning off, no boxes or points, a small output limit
6. **The worker bags while the check runs.** Only for flagged items, a second background call in **Point** mode marks where an item is, or where an unexpected one sits, so the screen can highlight it. Points are shorter answers than boxes, so they come back faster. Use Box only if a dot isn't clear enough.
7. **The manager gets a Photon text** when an error is caught or a warning is overridden, plus an end-of-shift summary (for example, "Caught 6 errors today. Most misses were sauces.").

### Station screen states
- **Green:** every item confirmed.
- **Amber (unsure):** names the item. One tap confirms it's there, and the tap is logged. Keeps false alarms from turning into ignored alarms.
- **Red:** names what's missing or wrong. **Stays on screen, tied to the order number, until someone resolves it**, so a late verdict still stops the bag before the courier takes it.

**Tune thresholds so we rarely flag correct orders**, even at the cost of missing a few more errors. If it cries wolf, workers ignore it within a day.

### Setup flow
- **Take reference photos through the station camera itself**, from the same mount, on the same mat, under the same lighting. Don't use a handheld phone. Perceptron's team said references should match the camera's view.
- **One photo per item should work.** Take 2–3 for harder items, rotating the item or moving it to a different spot on the mat between shots while the camera stays fixed.
- **Pick the mount angle (top-down or about 45°) before taking any references.** If the camera moves, retake them.
- Adding a new item takes under a minute, including by texting its photo to the Photon number.

### Time budget
| Step | Estimate |
| --- | --- |
| Capture, downscale, upload (phone hotspot) | 0.3–1.5 s |
| Model processing + about 50 output tokens | 1–8 s |
| Showing the result | under 0.1 s |
| **Total** | **about 2–10 s while the worker is already bagging.** Verify pickup timing with restaurants. |

### Cost and credits
- **$50 in Perceptron credits per person, so $150 across the team.** Rishabh has redeemed his and created a key. Use one key in the shared config so we watch a single balance; keep the other two as backups.
- A normal check (generous 20K input tokens, a few hundred output tokens) costs about **$0.003–0.004**, so $50 covers roughly **12,000–15,000 checks**. Even a maxed-out call stays under a cent.
- Planned use: about 70 calls for tests T1–T3, plus a few hundred for development and demo practice.
- **The real risk is a bug.** If the trigger misfires every frame, we'd hit 300 requests/minute and could burn $50 in about half an hour. **Build a cooldown between calls and a hard cap on total calls from the start.** Watch usage on Perceptron's dashboard.

### Handling opaque packaging
| Item type | Visible? | Strategy | Confidence |
| --- | --- | --- | --- |
| Cans, bottles, chips, cookies, packaged desserts | Yes | Recognize from reference photos | High |
| Containers by type (clamshell vs. cup vs. bowl) | Outside shape | Count by type | Medium-high |
| Lidded sauce cups | Partly (color shows through) | Reference photos; lookalikes need a lid sticker or marker | Medium; low for lookalikes |
| Fountain drinks | No | Read the lid sticker or marker, or just count cups | Medium with labels |
| Entrées in identical containers | No | Read the label or marker ("CB", Toast stickers); otherwise only count | Medium-high with labels; none without |
| Modifiers ("no onion", "no ice") | No | Only through labels; out of scope otherwise | None |
| Utensils, napkins | Yes, but small | Detect, low priority | Medium |

### Limits we state, not fix
- Anything inside a closed container, or any modifier, is only checkable through lid labels.
- It needs an internet connection, since the model runs in the cloud.
- One order on the mat at a time.

### Privacy
- **The camera points only at the mat**, so workers' faces aren't recorded. Say this in the pitch; it answers the surveillance criticism Agot got.
- Kitchen tickets usually show an order number, the customer's first name, the platform, and the items, but no card numbers or addresses. Demo tickets are fake. For a real restaurant: crop or blur the name line before anything goes to the API, and store nothing beyond the item list.

---

## 5. Not in version 1

| Idea | Decision |
| --- | --- |
| **Second camera angle** (William's suggestion) | **Deferred.** It helps when items hide each other or a label faces sideways, but doubles calls or forces combining two views without counting items twice. The spread-out rule and multiple reference photos cover most of it. **If T2 shows hidden items are the top cause of misses**, add a second view only for items marked `unsure`. |
| Tracking items continuously as they go into the bag | **Cut** (section 4). |
| Ingredient-level stockout tracking | **Dropped** (PreciTaste exists; orders are digital). |
| Pickup mix-up detection | Not chosen; harder to demo convincingly. |
| Menu price optimization (from the Atoms talk) | Needs sales data we don't have; hard to make memorable. |
| Real-time multi-stop delivery routing (from the Atoms talk) | Optimization-heavy and visually dull to demo. |
| **Arduino** (handed out at the event) | **Not needed.** Only useful with a load cell and amplifier board for the scale stretch goal, and nobody on the team has hardware experience. A red/green light would duplicate the screen. |
| **Stretch: camera plus a scale** | Put a $15 kitchen scale under the mat and read its display in the same photo. The camera catches light items; weight catches anything heavy. Two signals also mean fewer false alarms. Risk: the model may misread seven-segment digits, so test early. Only if everything else works. |

---

## 6. Positioning and expected judge questions

- **vs. DoorDash SmartScale:** it learns the order is too light. We name the missing item, including sauces and utensils a scale can't reliably detect, with no new hardware beyond a phone.
- **vs. Atoms, Agot, and PreciTaste:** custom models or special sensors, set up per restaurant, aimed at big chains. Ours is set up in minutes with a phone and no training, aimed at independent restaurants.
- **vs. Intel's open-source Order Accuracy:** also untrained, but it matches on item names, runs on a GPU server set up by an integrator, and only reports results. We match on the restaurant's own photos, run from a phone, and act on errors. Tradeoff to admit: we need internet and pay per call; theirs runs locally.

| Expected question | Our answer |
| --- | --- |
| "Intel already open-sourced this." | Intel shows a pre-trained model can check orders by item name. We add the restaurant's own reference photos, which is what separates lookalikes, and our comparison shows how much that helps. And an owner can set ours up with a phone instead of a GPU server. |
| "Why not just use YOLO?" | Out of the box it doesn't know your menu; it needs fine-tuning on a lot of data, which is exactly what Atoms said. Show the baseline comparison. |
| "Why Perceptron instead of any general vision model?" | Cost per order, grounded boxes for highlighting, and in-context learning from reference photos. Ideally show a comparison on the same test set. |
| "Did you just tune this to your demo?" | Held-out item numbers, plus let the judge add their own item live. |
| "Workers won't set items out first." | Atoms' own demo does exactly that, many kitchens already gather orders on a counter, and the auto-trigger needs no buttons. Back it up with an Ave restaurant quote. |
| "What about modifiers?" | Only through labels. Say it before they ask. |
| "Atoms answers in 100 ms; you take seconds." | The check happens before the bag is sealed, where a few seconds is fine, and the red flag stays up until resolved. |

---

## 7. Proving it generalizes

**The key demo move: let a judge add a brand-new item on the spot.** A judge grabs something off the snack table, photographs it once, adds it to a ticket, and watches the system catch it missing a minute later. That demonstrates the whole no-training claim live. Build the setup flow so this takes under a minute.

1. **Hold some items out.** Split items into a set we tune prompts and thresholds on, and a set we don't touch until the final test. Report held-out accuracy separately.
2. **Build two or three different menus** (for example, a burger place, a bubble tea shop, a poke place). Same code; only the reference photos change.
3. **Keep the prompt generic.** Item names and photos come only from setup data, never from hand-written rules about specific items. Say this to judges.
4. **Change the conditions:** lighting, angles, clutter on the mat, items touching. Report where it breaks.
5. **Compare against an untrained off-the-shelf detector** (for example, an open-vocabulary YOLO model) on the same held-out items. That turns "you'd need to fine-tune YOLO" into a number we measured.
6. **Run names-only vs. names-plus-photos.** Send the same test set through Perceptron twice: once with only the item names (Intel's approach), once with names plus reference photos. **If the photos catch lookalikes the names miss, that's our headline result.**
7. **Name the limits ourselves:** lookalikes without labels and anything inside a closed container. Judges trust a team that shows where its system fails.

---

## 8. Tracks

| Track | Fit |
| --- | --- |
| **Cook Smarter** (title) | Business efficiency, operations, automation; fits the "Let's Get Cookin'" theme |
| **Perceptron** | Reading text, grounding, in-context learning, and a clear chain from seeing to acting. (The 20-team cap applies only to Perceptron's robot arm track, not ours.) |
| **Photon** | Manager alerts, shift summaries, adding menu items by text |
| **DubHacks NEXT** | Clear buyer (restaurant owners) and a revenue story (error rate × refund and comp costs) |
| **Best Freshman Beginner's Project** | Confirm eligibility rules with organizers |

---

## 9. Team

- **Roy:** agent systems, Java, Python
- **William:** some CV (CNN) experience, front-end development
- **Rishabh:** Python (data pipelines and scientific computing on climate/atmospheric data in a UW research lab, contributed a fix to an open-source atmospheric detection repo), physics/math modeling (regressions and flight/apogee simulation from rocketry, differential equations), signal/data processing, GitHub Actions CI, learning CUDA; interested in controls, estimation, physical AI; no hardware experience

## 10. Roles

- **William:** camera capture, automatic trigger, local QR decoding, the reference-photo setup flow, and the station screen.
- **Roy:** mock order queue and tickets, the Perceptron request layer (schema, references per ticket, follow-up box calls, call cooldown and cap), and the Photon manager agent.
- **Rishabh:** the T1–T3 test harness and the go/no-go call; held-out evaluation, the untrained-detector baseline, and the names-only vs. names-plus-photos comparison; thresholds for `unsure`; the cost and ROI numbers; the scale stretch goal.

---

## 11. Saturday plan

**No coding before 12:30 PM.** Reading docs and making accounts is allowed.

*The task checklist near the top tracks progress. This section is the schedule.*

**Morning (done)**
1. Checked in at 9:30.
2. Perceptron credits redeemed and key created.
3. Meals are expected to be provided at DubHacks, so we only need packaging, not lunch.

**12:30 to about 3 PM: test before building much**
1. Rishabh builds the test harness first. Roy writes the Perceptron request. William gets camera capture and the auto-trigger working.
2. Perceptron's 1:30 PM workshop: done (findings in section 3). Take a real failure example to HUB 307 for prompting help.
3. Run T1–T3 on a teammate's phone hotspot with real containers.
4. Go/no-go call by 3 PM.

**2 to 4 PM:** one person walks the Ave for restaurant chats (section 13) and picks up props on the way. The University Book Store closes at 6 PM.

**Before 6 PM:** anything from the University Book Store. Safeway is open until 1 AM for anything else.

**Afternoon and evening:** build the real loop. William on the station screen, Roy on the order queue and Photon texts, Rishabh on thresholds, held-out evaluation, baseline comparison, and cost numbers.

**Saturday night:** record a backup demo video once the full loop works (Devpost needs one anyway). Sleep before the 10 AM Sunday deadline.

### Pass/fail tests (decide by about 3 PM)
| Test | Setup | Pass if |
| --- | --- | --- |
| **T1 latency** | 20 calls: one laid-out order photo, 5 reference photos, JSON checklist, reasoning off, over a phone hotspot | Median ≤ 4 s **and** 90th percentile ≤ 8 s |
| **T2 accuracy** | 20 laid-out orders, each with one deliberate error (missing sauce, swapped drink, missing side), plus 10 correct orders | Catches ≥ 16/20 errors **and** ≤ 2/10 false alarms |
| **T3 lookalikes and labels** | Two similar lidded sauces; identical clamshells with marker writing | Lookalikes told apart **or** marker reading ≥ 9/10 |

### Fallbacks
- **T1 fails:** the doc's earlier fallback, running the open-weight Isaac 0.1 locally, is weak: our MacBook has no NVIDIA GPU and its local speed is unverified. Realistic options are keeping the check fully asynchronous (the red flag still stops the bag), narrowing scope, or switching ideas.
- **T2 or T3 fails:** narrow the scope to labels plus container counts, or switch to the **Visual AirTag** idea (same reference-photo matching, and a lost-item match can wait 10 seconds).
- **Both T1 and T2 fail:** switch ideas by 4 PM.

---

## 12. Demo plan

### Table setup
- **Station screen** on the MacBook; the iPhone connects **by cable** through Continuity Camera.
- **Mat:** a plain, matte, solid color, edges taped. It gives contrast so plain packaging stands out, a fixed area for the trigger and crop, and the same surface for tests and judging. **Pick a color that contrasts with the containers:** if clamshells and sauce cups are white, use a dark or bold color, not white. Avoid anything glossy or patterned.
  - Fastest: flattened cardboard from a delivery or pizza box (free, matte, brown contrasts with white).
  - For testing right now: a dark hoodie or jacket laid flat, with no logo in frame.
  - Best: dark or bold poster board from the University Book Store (open until 6 PM).
- **Mount**, in order of preference:
  1. **The bridge:** two chairs back to back about two feet apart, a broom handle, yardstick, or cardboard tube across their tops, phone taped in the middle facing down. Mat on the floor or a low table between them.
  2. **The overhang:** a ruler or stiff cardboard strip taped so it sticks out from a weighted stack of boxes or books, phone taped at the end facing down.
  3. **An angled view:** phone propped at about 45° at the edge of the mat. The model doesn't need a straight-down view, and an angle shows can labels better. Spread items so nothing hides behind anything else.
  4. **Borrow or buy:** ask the organizers' hardware desk for a tripod, or get a cheap one ($15–25) at Target in the U District.
- Keep the mount within cable reach of the Mac, and **don't move it between tests and the demo**, or accuracy numbers and reference photos stop applying.
- **Network:** a teammate's phone hotspot as the main connection (the camera phone can't share its own), or Ethernet through a USB-C adapter if the venue has open ports. Wi-Fi with 1,200 hackers is a risk.
- Consistent camera angle and lighting.

### Tickets
Copy a real kitchen ticket. The big order number and the QR code are what matter; the rest is for realism. Lid markers should match (like "CB" for cheeseburger).

```
DUB BURGERS — DOORDASH
ORDER #4127            12:41 PM
Customer: Alex

1x Cheeseburger
   - no onion
1x Fries (large)
2x Ranch cup
1x Coke (can)

[QR code: order 4127]
```

If printing is a hassle, show tickets on a second phone placed on the mat.

### Items
- **The Dub Street cook:** ask for a few empty clamshells, sauce cups with lids, and to-go bags.
- **Ave restaurants:** ask for empties during visits, and photograph their packing stations and containers.
- **Event food:** different soda cans, chip bags, cookies, condiment packets.
- **Safeway** (4732 Brooklyn Ave NE, open until 1 AM) or **Trader Joe's** (4555 Roosevelt Way NE, open until 9 PM): cheap lidded portion cups, filled with ketchup, mustard, or ranch, plus lookalike drinks. Food doesn't need to be fresh.
- **University Book Store** (4326 University Way NE, open until 6 PM Saturday): poster board, marker, painter's tape, maybe a phone tripod.
- **Lookalikes on purpose** (two white sauces, Coke vs. Diet Coke) so we know the hard cases.

### The 60-second loop
1. A judge picks a ticket and sets out the order but leaves out the ranch.
2. About 3 s later the screen turns red with "Missing: ranch cup", and the manager's phone gets a text.
3. The judge adds the ranch and the screen turns green.
4. **Then the judge adds their own item** from the snack table, photographs it, puts it on a new ticket, and watches it get caught.

Say the limits before judges ask: "We check what's visible and labeled. We don't open containers."

---

## 13. Restaurant visits

Visits are for validation and pitch material, not the demo. Aim for 15-minute chats between 2 and 4 PM, after the lunch rush. One owner quote is strong material; a pilot is a bonus.

Ask:
- How often do orders go out wrong? Which items go missing most?
- What does a missing item cost you (refunds, delivery-app penalties, reviews)?
- Do you gather an order on the counter before bagging?
- How long does a bag usually wait before pickup?
- Do you label lids or containers?
- Can we photograph your packing station and a sample ticket, with the name covered?
- Would you try this free for a week?

---

## 14. How likely each piece is to work by Sunday 10 AM

| Piece | Confidence | Notes |
| --- | --- | --- |
| Mock order queue, tickets with QR codes, station screen | High | Ordinary web development |
| Phone capture, auto-trigger, local QR decoding | High | OpenCV |
| Perceptron call returning a JSON checklist | High that it runs; medium that it's accurate | Depends on reference photos and lighting |
| Distinct visible items | Medium-high | |
| Live enrollment of a judge's item | Medium-high | Same path as setup; practice it |
| Lookalike lidded items without labels | **Low** | Require lid markers in the demo, and say so |
| Reading labels and lid markers | Medium-high | |
| **Median latency ≤ 4 s on a hotspot** | **Unknown, leaning positive** | Perceptron's team expects a few seconds. Still the biggest risk; measure first. |
| Photon manager alerts | Medium | Beta went live Oct 15 |
| Camera plus scale | Medium-low | Stretch only |

**Overall:** buildable in about 21 hours **if** T1 and T2 pass. The demo is a few-second check on a laid-out order, not a camera that watches everything.

---

## 15. Open questions

1. **Perceptron (answered):** we have Mk1.5; credits are $50 per person; a check should take a few seconds; the rate limit is probably per key; one reference photo should work, and references should match the camera's view.
2. **Perceptron (still open, ask at HUB 307 with a real example):** Do references need a box drawn around the item, or is a cropped photo enough? Does reference matching work in Text mode, or only with boxes or points? Tips for lookalikes? Is the zoom tool worth its extra time for small items? How well does it read marker on lids? Does enforcing a JSON schema slow it down? What do the perceptive-track judges value most, and would they value the names-only vs. names-plus-photos comparison?
3. **Photon:** Is texting the manager the right fit for the track, or does it read as an add-on? Do we have a Mac set up for iMessage testing?
4. **Organizers:** Best Freshman track eligibility rules. Does the hardware desk lend tripods?
5. **Restaurants:** the questions in section 13.

---

## Sources

- **Perceptron:** [Mk1.5 launch post](https://www.perceptron.inc/blog/introducing-perceptron-mk1-5) · [docs](https://docs.perceptron.inc) · [scaling](https://docs.perceptron.inc/perceptron-mk1.5/guides/scaling.md) · [tokenization](https://docs.perceptron.inc/perceptron-mk1.5/guides/tokenization.md) · [in-context learning](https://docs.perceptron.inc/perceptron-mk1.5/capabilities/in-context-learning-image.md) · [reasoning](https://docs.perceptron.inc/perceptron-mk1.5/capabilities/thinking.md) · [video tracking](https://docs.perceptron.inc/perceptron-mk1.5/capabilities/video-tracking.md) · [Mk1 quickstart](https://docs.perceptron.inc/perceptron-mk1/index) · [Isaac 0.1](https://huggingface.co/PerceptronAI/Isaac-0.1)
- **Third-party speed measurements:** [OpenRouter Mk1](https://openrouter.ai/perceptron/perceptron-mk1) · [OpenRouter comparison](https://openrouter.ai/compare/openai/gpt-5.6-sol/perceptron/perceptron-mk1) · [modelgrep](https://modelgrep.com/best/lowest-latency/perceptron) · [thegtmdirectory](https://thegtmdirectory.com/models/perceptron-perceptron-mk1/perceptron-mk1) · [VentureBeat](https://venturebeat.com/technology/perceptron-mk1-shocks-with-highly-performant-video-analysis-ai-model-80-90-cheaper-than-anthropic-openai-and-google)
- **Existing products:** [Intel Order Accuracy repo](https://github.com/intel-retail/order-accuracy) · [Intel Dine-In how it works](https://github.com/intel-retail/order-accuracy/blob/main/docs/user-guide/dine-in/how-it-works.md) · [Intel Order Accuracy overview](https://docs.openedgeplatform.intel.com/2026.2/_sources/edge-ai-suites/ai-suite-retail/order-accuracy/oa-how-it-works.md.txt) · [Agot AI on CNBC](https://www.cnbc.com/amp/2021/09/16/this-start-up-uses-computer-vision-to-get-your-fast-food-order-made-accurately-.html) · [Agot AI on TechCrunch](https://techcrunch.com/2022/02/11/agot-ai-gives-restaurants-computer-vision-to-see-where-food-orders-go-wrong) · [Agot AI funding](https://hospitalitytech.com/agot-ai-raises-12-million-develop-build-computer-vision-tech-foodservice) · [Agot AI criticism (The Takeout)](https://thetakeout.com/startup-wrong-food-drive-thru-order-1847695904) · [PreciTaste Station Assistant](https://builders.intel.com/docs/networkbuilders/precitaste-station-assistant-1736257450.pdf) · [PreciTaste at Chipotle](https://www.deeplearning.ai/the-batch/chipotle-tests-ai-for-predicting-customer-demand) · [DoorDash SmartScale](https://about.doordash.com/en-au/news/doordash-launches-smartscale-for-smarter-deliveries) · [ACRELEC Double-Check](https://acrelec.com/double-check/) · [weight-check patent](https://patents.justia.com/patent/6115695) · [Toast item labels](https://support.toasttab.com/en/article/How-to-Set-Up-Print-Item-Labels)
- **Error rates:** [Intouch Insight 2025 drive-thru study](https://intouchinsight.com/blog/drive-thru-trends) · [eduMe via Restaurant Dive](https://www.restaurantdive.com/news/study-diners-are-dependent-on-food-delivery-but-are-sensitive-to-order-inaccuracies/623372/)
- **Continuity Camera:** [Apple Support](https://support.apple.com/102546)
- **Our own material:** Perceptron workshop transcript (Oct 17), Atoms talk transcript (`atoms-talk-transcript.md`, automatic transcription) and notes from the Dub Street Burgers cook interview.
