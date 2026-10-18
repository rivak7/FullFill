// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { AnnotatedPhoto } from "../src/features/orders/AnnotatedPhoto";
import type { Observations } from "../src/api/generated/contracts";

it("positions only valid model boxes on the exact captured photo and toggles them without a request", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const container = document.createElement("div");
  const root = createRoot(container);
  const box = { x_min: 100, y_min: 200, x_max: 700, y_max: 800 };
  const observations: Observations = { capture_id: "check", targets: [
    { target_id: "salad", status: "unsure", observed_quantity: 1, boxes: [box, { ...box, x_max: 0 }] },
    { target_id: "missing", status: "missing", observed_quantity: 0, boxes: [box] },
  ], unexpected_items: [{ name: "Cup", boxes: [{ ...box, x_min: 800, x_max: 1000 }] }] };
  const props = { image: "data:image/jpeg;base64,test", observations,
    targets: [{ target_id: "salad", item_id: "salad", name: "Corn salad", expected_quantity: 1, line_ids: ["line"] }] };
  try {
    await act(async () => root.render(<AnnotatedPhoto {...props} modelInput />));
    const boxes = container.querySelectorAll<HTMLElement>(".cv-object-box");
    expect(boxes).toHaveLength(2);
    expect(boxes[0].getAttribute("aria-label")).toBe("Corn salad · unsure");
    expect(boxes[0].style.left).toBe("10%");
    expect(boxes[0].style.top).toBe("20%");
    expect(boxes[0].style.width).toBe("60%");
    expect(boxes[0].style.height).toBe("60%");
    expect(boxes[1].className).toContain("unexpected");
    await act(async () => container.querySelector<HTMLInputElement>("input")!.click());
    expect(container.querySelectorAll(".cv-object-box")).toHaveLength(0);
    await act(async () => container.querySelector<HTMLInputElement>("input")!.click());
    expect(container.querySelectorAll(".cv-object-box")).toHaveLength(2);
    await act(async () => root.render(<AnnotatedPhoto {...props} modelInput={false} />));
    expect(container.querySelectorAll(".cv-object-box")).toHaveLength(0);
    expect(container.textContent).toContain("No object locations");
  } finally { await act(async () => root.unmount()); vi.unstubAllGlobals(); }
});
