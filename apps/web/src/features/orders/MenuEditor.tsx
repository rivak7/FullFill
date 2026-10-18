import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, orderApi, type MenuEdit, type MenuEntry, type MenuSnapshot } from "../../api/client";
import { MenuPhotoPicker } from "./MenuPhotoPicker";

type Draft = Omit<MenuEdit, "price_cents"> & { price: string; savedPhotoUrl: string | null };
type Attempt = { body: MenuEdit; key: string; action: "save" | "delete" };
const money = (cents: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
const draftFor = (item: MenuEntry): Draft => ({ item_id: item.item_id, name: item.name, price: (item.price_cents / 100).toFixed(2), available: item.available, archived: item.archived, version: item.version, savedPhotoUrl: item.photo_url });

export function MenuEditor() {
  const [menu, setMenu] = useState<MenuSnapshot | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pending, setPending] = useState<Attempt | null>(null);
  const [busy, setBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const menuEpoch = useRef(0);
  const saving = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const epoch = menuEpoch.current;
      try {
        if (saving.current) return;
        const next = await orderApi.managedMenu(controller.signal);
        if (!controller.signal.aborted && epoch === menuEpoch.current) setMenu(next);
      } catch (error) {
        if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Could not load the menu.");
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 10000);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh]);

  function select(item: MenuEntry) {
    setDraft(draftFor(item)); setPending(null); setError(null); setNotice(""); setConfirmDelete(false); setPhotoBusy(false);
  }
  function add() {
    setDraft({ item_id: "item_" + crypto.randomUUID().replaceAll("-", ""), name: "", price: "", available: true, archived: false, version: 0, savedPhotoUrl: null });
    setPending(null); setError(null); setNotice(""); setConfirmDelete(false); setPhotoBusy(false);
  }

  async function submit(attempt: Attempt) {
    saving.current = true; menuEpoch.current++;
    setPending(attempt); setBusy(true); setError(null); setNotice("");
    try {
      const next = await orderApi.saveMenu(attempt.body, attempt.key);
      setMenu(next); setPending(null); setDraft(null); setConfirmDelete(false); setPhotoBusy(false);
      setNotice(attempt.action === "delete" ? "Item deleted." : "Item saved.");
    } catch (error) {
      if (error instanceof ApiError && [400, 403, 409, 413, 422].includes(error.status)) setPending(null);
      setError(error instanceof Error ? error.message : "Could not save. Retry this change.");
      setRefresh(value => value + 1);
    } finally { saving.current = false; setBusy(false); }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy || photoBusy) return;
    if (pending) { void submit(pending); return; }
    if (!/^\d+(\.\d{1,2})?$/.test(draft.price) || Number(draft.price) > 10000) { setError("Enter a price between $0 and $10,000, with up to two decimal places."); return; }
    if (!draft.version && !draft.photo) { setError("Add a photo before saving this item."); return; }
    void submit({ key: crypto.randomUUID(), action: "save", body: {
      item_id: draft.item_id, name: draft.name.trim(), price_cents: Math.round(Number(draft.price) * 100),
      available: draft.available, archived: false, version: draft.version, ...(draft.photo ? { photo: draft.photo } : {}),
    } });
  }

  const visible = menu?.items.filter(item => !item.archived) ?? [];
  const latest = menu?.items.find(item => item.item_id === draft?.item_id);
  const changedElsewhere = !!(latest && draft && (latest.archived || latest.version !== draft.version));
  const locked = busy || !!pending;
  const canSave = !!draft?.name.trim() && !!draft.price && (!!draft.version || !!draft.photo) && !changedElsewhere && !photoBusy;

  function remove() {
    if (!draft || !latest || locked || photoBusy || changedElsewhere) return;
    void submit({ key: crypto.randomUUID(), action: "delete", body: {
      item_id: latest.item_id, name: latest.name, price_cents: latest.price_cents,
      available: latest.available, archived: true, version: draft.version,
    } });
  }

  return <main className="menu-management">
    <div className="menu-management-heading"><h1>Menu</h1>
      <div className="menu-actions"><button className="primary-button" disabled={locked || !!draft} onClick={add}>+ Add item</button></div>
    </div>
    {notice && <p className="success-banner" role="status">{notice}</p>}
    {!draft && error && <p className="error-banner" role="alert">{error}</p>}
    <div className="menu-management-layout">
      <section aria-label="Menu items">
        {!menu && <p role="status">Loading menu…</p>}
        {menu && !visible.length && <p className="menu-empty">Add your first menu item.</p>}
        {visible.map(item => <article className="managed-menu-item" key={item.item_id}>
          {item.photo_url ? <img className="menu-item-thumbnail" src={item.photo_url} alt={item.name} loading="lazy" /> : <span className="menu-item-thumbnail missing-photo">No photo</span>}
          <div><h2>{item.name}</h2><span>{money(item.price_cents)}</span></div>
          <span className={`availability ${item.available ? "available" : "sold-out"}`}>{item.available ? "Available" : "Sold out"}</span>
          <button className="secondary-button" aria-label={`Edit ${item.name}`} disabled={locked || !!draft} onClick={() => select(item)}>Edit</button>
        </article>)}
      </section>
      {draft ? <form className="menu-edit-card" onSubmit={save}>
        <h2>{draft.version ? "Edit item" : "New item"}</h2>
        {changedElsewhere && <div className="error-banner" role="alert">{latest?.archived ? "This item was deleted on another screen." : <>This item changed on another screen. <button type="button" disabled={locked || photoBusy} onClick={() => latest && select(latest)}>Reload item</button></>}</div>}
        <fieldset disabled={locked}>
          <MenuPhotoPicker key={draft.item_id + ":" + draft.version} photo={draft.photo} savedUrl={draft.savedPhotoUrl} disabled={locked || changedElsewhere} onChange={photo => setDraft(current => current ? { ...current, photo } : null)} onBusyChange={setPhotoBusy} />
          <label htmlFor="item-name">Name</label><input id="item-name" value={draft.name} maxLength={120} required onChange={event => setDraft({ ...draft, name: event.target.value })} />
          <label htmlFor="item-price">Price ($)</label><input id="item-price" inputMode="decimal" value={draft.price} required onChange={event => setDraft({ ...draft, price: event.target.value })} />
          <label className="check-label"><input type="checkbox" checked={draft.available} onChange={event => setDraft({ ...draft, available: event.target.checked })} />Available to order</label>
        </fieldset>
        {error && <p className="error-banner" role="alert">{error}</p>}
        <div className="edit-actions"><button type="button" className="secondary-button" disabled={locked || photoBusy} onClick={() => { setDraft(null); setError(null); }}>Cancel</button><button className="primary-button" disabled={busy || (!pending && !canSave)}>{busy ? "Saving…" : pending ? "Retry save" : "Save item"}</button></div>
        {!!draft.version && !draft.archived && <div className="delete-item">
          {confirmDelete ? <><p>Delete {latest?.name}?</p><div className="photo-actions"><button type="button" className="secondary-button" disabled={locked} onClick={() => setConfirmDelete(false)}>Keep item</button><button type="button" className="danger-button" disabled={locked || photoBusy || changedElsewhere} onClick={remove}>Delete</button></div></>
            : <button type="button" className="delete-link" disabled={locked || photoBusy || changedElsewhere} onClick={() => setConfirmDelete(true)}>Delete item</button>}
        </div>}
      </form> : <aside className="menu-editor-hint"><span>↖</span><p>Select an item to edit its photo, name, or price.</p></aside>}
    </div>
  </main>;
}
