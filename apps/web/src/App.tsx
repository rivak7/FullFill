import { useEffect, useState } from "react";
import { OrderingScreen } from "./features/orders/OrderingScreen";
import { FulfillmentScreen } from "./features/orders/FulfillmentScreen";
import { StationScreen } from "./features/station/StationScreen";
import { scenarios } from "./features/station/fakeOrders";
import { AccessGate } from "./features/access/AccessGate";
import { MenuEditor } from "./features/orders/MenuEditor";
import { homePath, siteScreen } from "./site";
import { SettingsMenu } from "./features/orders/SettingsMenu";
import "./app.css";

export function App() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  const ordering = siteScreen === "order" || (siteScreen === "combined" && path === "/order");
  const valid = path === "/" || (siteScreen === "combined" ? ["/order", "/fulfill"].includes(path) : path === `/${siteScreen}`);
  const [menu, setMenu] = useState(() => window.location.hash === "#menu");
  useEffect(() => {
    const update = () => setMenu(window.location.hash === "#menu");
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  if (siteScreen === "combined" && path === "/demo") return <DemoScreen />;
  const kitchenPath = siteScreen === "combined" ? "/fulfill" : "/";
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href={homePath}><img className="brand-logo" src="/fullfill-wordmark.svg" alt="FullFill" /></a>
        {siteScreen !== "order" && <nav aria-label="Main navigation">
          <a href={kitchenPath} aria-current={!ordering && valid && !menu ? "page" : undefined}>Kitchen</a>
          <a href={`${kitchenPath}#menu`} aria-current={!ordering && valid && menu ? "page" : undefined}>Menu</a>
        </nav>}
        {!ordering && valid && <SettingsMenu />}
      </header>
      {!valid ? (
        <main className="empty-state"><h1>Page not found</h1><a href={homePath}>Go back</a></main>
      ) : <AccessGate scope={ordering ? "order" : "kitchen"}>{ordering ? <OrderingScreen /> : menu ? <MenuEditor /> : <FulfillmentScreen />}</AccessGate>}
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
