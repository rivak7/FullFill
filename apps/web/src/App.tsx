import { useEffect, useState } from "react";
import { OrderingScreen } from "./features/orders/OrderingScreen";
import { FulfillmentScreen } from "./features/orders/FulfillmentScreen";
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

