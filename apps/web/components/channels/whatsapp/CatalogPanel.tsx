"use client";

/* Catalog tab inside the WhatsApp hub.
 *
 * Styled with the hub's --wa-* tokens so it reads as the same product as
 * Profile / Numbers / Settings. Logic is unchanged: items CRUD, the public
 * share link, and the tenant's databank-grounding switch.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  createCatalogItem,
  createCatalogShare,
  deleteCatalogItem,
  getCatalogShare,
  listCatalogItems,
  revokeCatalogShare,
  updateCatalogItem,
  type CatalogItem,
} from "@/lib/api-catalog";

interface ChannelRow {
  id: string;
  platform: string;
  display_name: string | null;
}

const MESSAGING = new Set(["whatsapp", "instagram", "facebook"]);
const CURRENCIES = ["SAR", "AED", "USD", "EUR", "GBP", "EGP", "KWD", "QAR", "OMR", "BHD"];

const CARD =
  "rounded-lg bg-[var(--wa-panel)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]";
const INPUT =
  "min-h-9 w-full rounded-lg border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3 text-[13px] text-[var(--wa-text)] outline-none focus:border-[var(--wa-accent)]";
const LABEL = "text-[11px] font-semibold text-[var(--wa-label)]";
const MUTED = "text-[12px] text-[var(--wa-text-2)]";

type Draft = {
  name: string;
  price: string;
  currency: string;
  description: string;
  image_url: string;
  item_url: string;
  in_stock: boolean;
};

const EMPTY: Draft = {
  name: "", price: "", currency: "SAR", description: "",
  image_url: "", item_url: "", in_stock: true,
};

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

export default function CatalogPanel() {
  const { t, locale } = useI18n();
  const k = t.catalog;
  const fmt = (n: number) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [adding, setAdding] = useState(false);

  const [sharePath, setSharePath] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [channels, setChannels] = useState<ChannelRow[]>([]);
  const [grounding, setGrounding] = useState(true);
  const [groundingBusy, setGroundingBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { items: rows } = await listCatalogItems(true);
      setItems(rows);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : k.errors.load);
    } finally {
      setLoading(false);
    }
  }, [k]);

  useEffect(() => {
    void refresh();
    getCatalogShare().then((s) => setSharePath(s.path)).catch(() => {});
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels?limit=100");
        const rows = (data?.channels ?? []).filter((c: ChannelRow) =>
          MESSAGING.has(c.platform),
        );
        setChannels(rows);
        if (rows.length) {
          const cfgs = await Promise.all(
            rows.map((c: ChannelRow) =>
              apiFetch(`/api/v1/channels/${c.id}/autoreply`).catch(() => null),
            ),
          );
          const values = cfgs.filter(Boolean).map((c) => c.databank_grounding !== false);
          setGrounding(values.length ? values.every(Boolean) : true);
        }
      } catch {
        /* switch hides without channels */
      }
    })();
  }, [refresh]);

  const activeCount = useMemo(() => items.filter((i) => i.active).length, [items]);

  const saveItem = async () => {
    if (!draft.name.trim() || busy) return;
    setBusy("add");
    try {
      await createCatalogItem({
        name: draft.name.trim(),
        price: draft.price.trim() ? draft.price.trim() : null,
        currency: draft.currency || null,
        description: draft.description.trim() || null,
        image_url: draft.image_url.trim() || null,
        item_url: draft.item_url.trim() || null,
        in_stock: draft.in_stock,
      });
      setDraft(EMPTY);
      setAdding(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : k.errors.add);
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (item: CatalogItem, patch: { in_stock?: boolean; active?: boolean }) => {
    setBusy(item.id);
    try {
      const updated = await updateCatalogItem(item.id, patch);
      setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
    } catch (e) {
      setError(e instanceof Error ? e.message : k.errors.update);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (item: CatalogItem) => {
    if (!window.confirm(fill(k.deleteConfirm, { name: item.name }))) return;
    setBusy(item.id);
    try {
      await deleteCatalogItem(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : k.errors.remove);
    } finally {
      setBusy(null);
    }
  };

  const toggleShare = async () => {
    setBusy("share");
    try {
      if (sharePath) {
        await revokeCatalogShare();
        setSharePath(null);
      } else {
        setSharePath((await createCatalogShare()).path);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : k.errors.link);
    } finally {
      setBusy(null);
    }
  };

  const rotateShare = async () => {
    if (!window.confirm(k.replaceConfirm)) return;
    setBusy("share");
    try {
      setSharePath((await createCatalogShare(true)).path);
    } catch (e) {
      setError(e instanceof Error ? e.message : k.errors.replace);
    } finally {
      setBusy(null);
    }
  };

  const copyShare = async () => {
    if (!sharePath) return;
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${sharePath}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError(k.copiedNote);
    }
  };

  const setGroundingForAll = async (next: boolean) => {
    if (!channels.length || groundingBusy) return;
    setGroundingBusy(true);
    const previous = grounding;
    setGrounding(next);
    try {
      await Promise.all(
        channels.map((c) =>
          apiFetch(`/api/v1/channels/${c.id}/autoreply`, {
            method: "PUT",
            body: JSON.stringify({ databank_grounding: next }),
          }),
        ),
      );
    } catch (e) {
      setGrounding(previous);
      setError(e instanceof Error ? e.message : k.errors.setting);
    } finally {
      setGroundingBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="rounded-lg bg-[var(--wa-warn-bg)] px-3 py-2 text-[12px] text-[var(--wa-warn-text)]">
          {error}
        </p>
      )}

      <section className={`${CARD} p-4`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-[var(--wa-text)]">{k.shareTitle}</h2>
            <p className={`mt-0.5 ${MUTED}`}>
              {k.shareDesc}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {sharePath && (
              <>
                <code className="max-w-[40vw] truncate rounded-full bg-[var(--wa-panel-2)] px-3 py-1 text-[11px] text-[var(--wa-text-2)]">
                  {sharePath}
                </code>
                <button onClick={() => void copyShare()} className="rounded-full border border-[var(--wa-accent)]/40 px-3 py-1 text-[11px] font-bold text-[var(--wa-accent-deep)]">
                  {copied ? k.copied : k.copy}
                </button>
                <button onClick={() => void rotateShare()} disabled={busy === "share"} className="rounded-full px-2 py-1 text-[11px] font-semibold text-[var(--wa-text-2)] disabled:opacity-40">
                  {k.replace}
                </button>
              </>
            )}
            <button
              onClick={() => void toggleShare()}
              disabled={busy === "share"}
              className={`rounded-full px-3 py-1.5 text-[11px] font-bold disabled:opacity-40 ${
                sharePath
                  ? "border border-[var(--wa-border)] text-[var(--wa-text-2)]"
                  : "bg-[var(--wa-accent)] text-white"
              }`}
            >
              {sharePath ? k.turnOff : k.createLink}
            </button>
          </div>
        </div>
      </section>

      {channels.length > 0 && (
        <section className={`${CARD} flex items-center justify-between gap-4 p-4`}>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-[var(--wa-text)]">
              {k.groundingTitle}
            </h2>
            <p className={`mt-0.5 ${MUTED}`}>
              {k.groundingDesc}
            </p>
          </div>
          <button
            role="switch"
            aria-checked={grounding}
            aria-label={k.groundingTitle}
            disabled={groundingBusy}
            onClick={() => void setGroundingForAll(!grounding)}
            className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50 ${
              grounding ? "bg-[var(--wa-accent)]" : "bg-[var(--wa-text-3)]/30"
            }`}
          >
            <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow-md transition-transform ${grounding ? "translate-x-[22px]" : "translate-x-0.5"}`} />
          </button>
        </section>
      )}

      <section className={CARD}>
        <div className="flex items-center justify-between border-b border-[var(--wa-border)] px-4 py-2.5">
          <h2 className="text-[14px] font-semibold text-[var(--wa-text)]">{k.items}</h2>
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-[var(--wa-text-3)]">
              {fill(k.activeOf, { a: fmt(activeCount), b: fmt(items.length) })}
            </span>
            <button onClick={() => setAdding((v) => !v)} className="rounded-full bg-[var(--wa-accent)] px-3 py-1 text-[11px] font-bold text-white">
              {adding ? k.close : k.addItem}
            </button>
          </div>
        </div>

        {adding && (
          <div className="border-b border-[var(--wa-border)] bg-[var(--wa-panel-2)] p-4">
            <div className="grid gap-2.5 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className={LABEL}>{k.name}</span>
                <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder={k.namePh} className={INPUT} autoFocus />
              </label>
              <div className="grid grid-cols-[1fr_90px] gap-2">
                <label className="flex flex-col gap-1">
                  <span className={LABEL}>{k.price}</span>
                  <input value={draft.price} onChange={(e) => setDraft({ ...draft, price: e.target.value })} inputMode="decimal" placeholder="85.00" className={INPUT} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className={LABEL}>{k.currency}</span>
                  <select value={draft.currency} onChange={(e) => setDraft({ ...draft, currency: e.target.value })} className={INPUT}>
                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
              </div>
              <label className="flex flex-col gap-1 sm:col-span-2">
                <span className={LABEL}>{k.description}</span>
                <input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder={k.descriptionPh} className={INPUT} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={LABEL}>{k.imageUrl}</span>
                <input value={draft.image_url} onChange={(e) => setDraft({ ...draft, image_url: e.target.value })} placeholder="https://…" className={INPUT} />
              </label>
              <label className="flex flex-col gap-1">
                <span className={LABEL}>{k.productLink}</span>
                <input value={draft.item_url} onChange={(e) => setDraft({ ...draft, item_url: e.target.value })} placeholder="https://…" className={INPUT} />
              </label>
            </div>
            <div className="mt-3 flex items-center justify-between">
              <label className="flex items-center gap-2 text-[12px] text-[var(--wa-text-2)]">
                <input type="checkbox" checked={draft.in_stock} onChange={(e) => setDraft({ ...draft, in_stock: e.target.checked })} className="h-4 w-4 accent-[var(--wa-accent)]" />
                {k.inStock}
              </label>
              <button onClick={() => void saveItem()} disabled={!draft.name.trim() || busy === "add"} className="rounded-full bg-[var(--wa-accent)] px-4 py-1.5 text-[11px] font-bold text-white disabled:opacity-40">
                {busy === "add" ? k.saving : k.saveItem}
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <p className="px-4 py-8 text-center text-[12px] text-[var(--wa-text-3)]">{k.loading}</p>
        ) : items.length === 0 ? (
          <p className="px-4 py-8 text-center text-[12px] text-[var(--wa-text-3)]">
            {k.noItems}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--wa-border)]">
            {items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                {item.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={item.image_url} alt="" className="h-9 w-9 rounded-lg bg-[var(--wa-panel-2)] object-cover" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                ) : (
                  <span className="h-9 w-9 rounded-lg bg-[var(--wa-accent)]/10" aria-hidden="true" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold text-[var(--wa-text)]">
                    {item.name}
                    {!item.active && (
                      <span className="ml-2 rounded-full bg-[var(--wa-panel-2)] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[var(--wa-text-3)]">
                        {k.hidden}
                      </span>
                    )}
                  </p>
                  <p className={`truncate ${MUTED}`}>
                    {item.price_display ?? k.noPrice}
                    {item.description ? ` · ${item.description}` : ""}
                  </p>
                </div>
                <button
                  onClick={() => void toggle(item, { in_stock: !item.in_stock })}
                  disabled={busy === item.id}
                  className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide disabled:opacity-40 ${
                    item.in_stock
                      ? "bg-[var(--wa-accent)]/12 text-[var(--wa-accent-deep)]"
                      : "bg-[var(--wa-panel-2)] text-[var(--wa-text-3)]"
                  }`}
                >
                  {item.in_stock ? k.inStock : k.out}
                </button>
                <button onClick={() => void toggle(item, { active: !item.active })} disabled={busy === item.id} className="rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--wa-text-3)] hover:text-[var(--wa-text)] disabled:opacity-40">
                  {item.active ? k.hide : k.show}
                </button>
                <button onClick={() => void remove(item)} disabled={busy === item.id} aria-label={fill(k.deleteAria, { name: item.name })} className="rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--wa-text-3)] hover:text-[#c4304b] disabled:opacity-40">
                  {k.delete}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="px-1 text-[11px] leading-5 text-[var(--wa-text-3)]">
        {k.footer}
      </p>
    </div>
  );
}
