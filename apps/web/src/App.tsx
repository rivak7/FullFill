import { useState } from "react";
import { OrderingScreen } from "./features/orders/OrderingScreen";
import { FulfillmentScreen } from "./features/orders/FulfillmentScreen";
import { StationScreen } from "./features/station/StationScreen";
import { scenarios } from "./features/station/fakeOrders";
import { AccessGate } from "./features/access/AccessGate";
import { MenuEditor } from "./features/orders/MenuEditor";
import { homePath, siteScreen } from "./site";
import "./app.css";

export function App() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  if (siteScreen === "combined" && path === "/demo") return <DemoScreen />;
  const ordering = siteScreen === "order" || (siteScreen === "combined" && path === "/order");
  const valid = path === "/" || (siteScreen === "combined" ? ["/order", "/fulfill"].includes(path) : path === `/${siteScreen}`);
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href={homePath}><img className="brand-logo" src="/fullfill-wordmark.svg" alt="FullFill" /></a>
        {siteScreen === "combined" ? <nav aria-label="Main navigation">
          <a href="/order" aria-current={ordering ? "page" : undefined}>Order</a>
          <a href="/fulfill" aria-current={!ordering && valid ? "page" : undefined}>Fulfillment</a>
        </nav> : <span className="site-label">{ordering ? "Order" : "Kitchen"}</span>}
        <span className="environment-label"><span />Test mode</span>
      </header>
      {!valid ? (
        <main className="empty-state"><h1>Page not found</h1><a href={homePath}>Go back</a></main>
      ) : <AccessGate>{ordering ? <OrderingScreen /> : <KitchenScreen />}</AccessGate>}
    </div>
  );
}

function KitchenScreen() {
  const [menu, setMenu] = useState(window.location.hash === "#menu");
  function navigate(value: boolean) { setMenu(value); window.history.replaceState(null, "", window.location.pathname + window.location.search + (value ? "#menu" : "")); }
  return <>
    <nav className="kitchen-tabs" aria-label="Kitchen navigation"><button aria-current={!menu ? "page" : undefined} onClick={() => navigate(false)}>Orders</button><button aria-current={menu ? "page" : undefined} onClick={() => navigate(true)}>Menu</button></nav>
    {menu ? <MenuEditor /> : <FulfillmentScreen />}
  </>;
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
