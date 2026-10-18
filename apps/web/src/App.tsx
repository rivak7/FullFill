import { useState } from "react";
import { OrderingScreen } from "./features/orders/OrderingScreen";
import { FulfillmentScreen } from "./features/orders/FulfillmentScreen";
import { StationScreen } from "./features/station/StationScreen";
import { scenarios } from "./features/station/fakeOrders";
import "./app.css";

export function App() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  if (path === "/demo") return <DemoScreen />;
  const ordering = path === "/order";
  const valid = ordering || path === "/fulfill" || path === "/";
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="/fulfill"><span className="brand-mark">ff</span> FullFill</a>
        <nav aria-label="Main navigation">
          <a href="/order" aria-current={ordering ? "page" : undefined}>Order</a>
          <a href="/fulfill" aria-current={!ordering && valid ? "page" : undefined}>Fulfillment</a>
        </nav>
        <span className="environment-label"><span />Test mode</span>
      </header>
      {!valid ? (
        <main className="empty-state"><h1>Page not found</h1><a href="/fulfill">Open fulfillment</a></main>
      ) : ordering ? <OrderingScreen /> : <FulfillmentScreen />}
    </div>
  );
}

function DemoScreen() {
  const [key, setKey] = useState("amber");

  return (
    <>
      <StationScreen state={scenarios[key].state} />
      <nav className="demo-bar" aria-label="Demo scenarios">
        <a href="/fulfill">Live queue</a>
        {Object.entries(scenarios).map(([k, s]) => (
          <button key={k} aria-pressed={k === key} onClick={() => setKey(k)}>
            {s.label}
          </button>
        ))}
      </nav>
    </>
  );
}
