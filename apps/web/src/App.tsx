import { useState } from "react";
import type { OrderState } from "./api/generated/contracts";
import { StationScreen } from "./features/station/StationScreen";
import { scenarios } from "./features/station/fakeOrders";

// Runs on fake results until StationApi is implemented. Swap `state` for the
// order from StationApi.getStation/subscribe, and send onConfirm to StationApi.confirm.
export function App() {
  const [key, setKey] = useState("amber");
  const [state, setState] = useState<OrderState>(scenarios.amber.state);

  function pick(next: string) {
    setKey(next);
    setState(scenarios[next].state);
  }

  return (
    <>
      <StationScreen state={state} onConfirm={() => setState({ ...state, disposition: "overridden" })} />
      <nav className="demo-bar" aria-label="Demo scenarios">
        {Object.entries(scenarios).map(([k, s]) => (
          <button key={k} aria-pressed={k === key} onClick={() => pick(k)}>
            {s.label}
          </button>
        ))}
      </nav>
    </>
  );
}
