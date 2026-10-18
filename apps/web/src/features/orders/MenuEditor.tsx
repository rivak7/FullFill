import { useEffect, useState, type FormEvent } from "react";
import { ApiError, hasMenuKey, orderApi, setMenuKey, type MenuEdit, type MenuEntry, type MenuSnapshot } from "../../api/client";

type Draft = Omit<MenuEdit, "price_cents"> & { price: string };
const money = (cents: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
const draftFor = (item: MenuEntry): Draft => ({ item_id: item.item_id, name: item.name, price: (item.price_cents / 100).toFixed(2), available: item.available, archived: item.archived, version: item.version });

export function MenuEditor() {
  const [unlocked, setUnlocked] = useState(hasMenuKey);
  const [code, setCode] = useState("");
  const [menu, setMenu] = useState<MenuSnapshot | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pending, setPending] = useState<{ body: MenuEdit; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!unlocked) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await orderApi.managedMenu(controller.signal);
        if (!controller.signal.aborted) setMenu(next);
      } catch (error) {
        if (!controller.signal.aborted) {
          if (error instanceof ApiError && error.status === 403) { setMenuKey(""); setUnlocked(false); }
          setError(error instanceof Error ? error.message : "Could not load the menu.");
        }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 10000);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [unlocked, refresh]);

  async function unlock(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null); setMenuKey(code.trim());
    try { setMenu(await orderApi.managedMenu()); setUnlocked(true); setCode(""); }
    catch (error) { setMenuKey(""); setError(error instanceof Error ? error.message : "Could not unlock menu editing."); }
    finally { setBusy(false); }
  }

  function select(item: MenuEntry) { setDraft(draftFor(item)); setPending(null); setError(null); setNotice(""); }
  function add() {
    setDraft({ item_id: "item_" + crypto.randomUUID().replaceAll("-", ""), name: "", price: "", available: true, archived: false, version: 0 });
    setPending(null); setError(null); setNotice("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    if (!pending && (!/^\d+(\.\d{1,2})?$/.test(draft.price) || Number(draft.price) > 10000)) { setError("Enter a price between $0 and $10,000, with up to two decimal places."); return; }
    const attempt = pending ?? { key: crypto.randomUUID(), body: { item_id: draft.item_id, name: draft.name.trim(), price_cents: Math.round(Number(draft.price) * 100), available: draft.available, archived: draft.archived, version: draft.version } };
    setPending(attempt); setBusy(true); setError(null); setNotice("");
    try {
      const next = await orderApi.saveMenu(attempt.body, attempt.key);
      setMenu(next); setPending(null); setDraft(null); setNotice("Menu saved. Ordering screens update automatically.");
    } catch (error) {
      if (error instanceof ApiError && [403, 409, 422].includes(error.status)) setPending(null);
      if (error instanceof ApiError && error.status === 403) { setMenuKey(""); setUnlocked(false); }
      setError(error instanceof Error ? error.message : "Could not save. Retry this change.");
      setRefresh(value => value + 1);
    } finally { setBusy(false); }
  }

  if (!unlocked) return <main className="access-page"><form className="access-card" onSubmit={unlock}>
    <h1>Edit menu</h1><label htmlFor="menu-code">Menu editing code</label>
    <input id="menu-code" type="password" autoComplete="current-password" value={code} onChange={event => setCode(event.target.value)} required disabled={busy} />
    {error && <p className="error-banner" role="alert">{error}</p>}
    <button className="primary-button" disabled={busy || !code.trim()}>{busy ? "Connecting…" : "Unlock menu"}</button>
  </form></main>;

  const visible = menu?.items.filter(item => item.archived === showArchived) ?? [];
  const latest = menu?.items.find(item => item.item_id === draft?.item_id);
  const changedElsewhere = latest && draft && latest.version !== draft.version;
  return <main className="menu-management">
    <div className="menu-management-heading"><div><h1>Menu</h1><p>Changes appear on the ordering screen.</p></div>
      <div className="menu-actions"><button className="secondary-button" disabled={busy || !!pending} onClick={() => { setMenuKey(""); setUnlocked(false); }}>Lock editing</button><button className="primary-button" disabled={busy || !!pending || !!draft} onClick={add}>+ Add item</button></div>
    </div>
    {notice && <p className="success-banner" role="status">{notice}</p>}
    {!draft && error && <p className="error-banner" role="alert">{error}</p>}
    <div className="menu-management-layout">
      <section aria-label="Menu items"><div className="menu-filter" aria-label="Item filter"><button aria-pressed={!showArchived} onClick={() => setShowArchived(false)}>On the menu</button><button aria-pressed={showArchived} onClick={() => setShowArchived(true)}>Archived</button></div>
        {!menu && <p role="status">Loading menu…</p>}
        {menu && !visible.length && <p className="menu-empty">{showArchived ? "No archived items." : "Add your first menu item."}</p>}
        {visible.map(item => <article className="managed-menu-item" key={item.item_id}>
          <div><h2>{item.name}</h2><span>{money(item.price_cents)}</span></div>
          <span className={`availability ${item.archived ? "archived" : item.available ? "available" : "sold-out"}`}>{item.archived ? "Archived" : item.available ? "Available" : "Sold out"}</span>
          <button className="secondary-button" aria-label={`Edit ${item.name}`} disabled={busy || !!pending || !!draft} onClick={() => select(item)}>Edit</button>
        </article>)}
      </section>
      {draft ? <form className="menu-edit-card" onSubmit={save}>
        <h2>{draft.version ? "Edit item" : "New item"}</h2>
        {changedElsewhere && <div className="error-banner" role="alert">This item changed on another screen. <button type="button" disabled={busy || !!pending} onClick={() => select(latest)}>Reload item</button></div>}
        <fieldset disabled={busy || !!pending}><label htmlFor="item-name">Name</label><input id="item-name" value={draft.name} maxLength={120} required onChange={event => setDraft({ ...draft, name: event.target.value })} />
          <label htmlFor="item-price">Price ($)</label><input id="item-price" inputMode="decimal" value={draft.price} required onChange={event => setDraft({ ...draft, price: event.target.value })} />
          <label className="check-label"><input type="checkbox" checked={draft.available} onChange={event => setDraft({ ...draft, available: event.target.checked })} />Available to order</label>
          {!!draft.version && <label className="check-label"><input type="checkbox" checked={draft.archived} onChange={event => setDraft({ ...draft, archived: event.target.checked })} />Archived</label>}
        </fieldset>
        {error && <p className="error-banner" role="alert">{error}</p>}
        <div className="edit-actions"><button type="button" className="secondary-button" disabled={busy || !!pending} onClick={() => { setDraft(null); setError(null); }}>Cancel</button><button className="primary-button" disabled={busy || (!pending && (!!changedElsewhere || !draft.name.trim()))}>{busy ? "Saving…" : pending ? "Retry save" : "Save changes"}</button></div>
      </form> : <aside className="menu-editor-hint"><span>↖</span><p>Select an item to edit its price or availability.</p></aside>}
    </div>
  </main>;
}
