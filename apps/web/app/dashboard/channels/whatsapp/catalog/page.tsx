"use client";

/* Catalog: the items the assistant quotes, and the public link customers open.
 *
 * Kept deliberately compact. The backend owns price formatting, stock wording
 * and the prompt block; this page only manages rows and the share link.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import WhatsAppSubnav from "@/components/channels/whatsapp/WhatsAppSubnav";
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

const MESSAGING_PLATFORMS = new Set(["whatsapp", "instagram", "facebook"]);

const CURRENCIES = ["SAR", "AED", "USD", "EUR", "GBP", "EGP", "KWD", "QAR", "OMR", "BHD"];

type Draft = {
  name: string;
  price: string;
  currency: string;
  description: string;
  image_url: string;
  item_url: string;
  in_stock: boolean;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  price: "",
  currency: "SAR",
  description: "",
  image_url: "",
  item_url: "",
  in_stock: true,
};

export default function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
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
      setError(e instanceof Error ? e.message : "Could not load the catalog.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    getCatalogShare()
      .then((share) => setSharePath(share.path))
      .catch(() => setSharePath(null));
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels?limit=100");
        const rows = (data?.channels ?? []).filter((c: ChannelRow) =>
          MESSAGING_PLATFORMS.has(c.platform),
        );
        setChannels(rows);
        if (rows.length) {
          const configs = await Promise.all(
            rows.map((c: ChannelRow) =>
              apiFetch(`/api/v1/channels/${c.id}/autoreply`).catch(() => null),
            ),
          );
          const values = configs
            .filter(Boolean)
            .map((cfg) => cfg.databank_grounding !== false);
          setGrounding(values.length ? values.every(Boolean) : true);
        }
      } catch {
        /* the switch simply does not render without channels */
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
      setDraft(EMPTY_DRAFT);
      setAdding(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the item.");
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
      setError(e instanceof Error ? e.message : "Could not update the item.");
    } finally {
      setBusy(null);
    }
  };

  const remove = async (item: CatalogItem) => {
    if (!window.confirm(`Delete “${item.name}”? This cannot be undone.`)) return;
    setBusy(item.id);
    try {
      await deleteCatalogItem(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the item.");
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
        const share = await createCatalogShare();
        setSharePath(share.path);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the link.");
    } finally {
      setBusy(null);
    }
  };

  const rotateShare = async () => {
    if (!window.confirm("Replace the link? The old one stops working immediately.")) return;
    setBusy("share");
    try {
      const share = await createCatalogShare(true);
      setSharePath(share.path);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not replace the link.");
    } finally {
      setBusy(null);
    }
  };

  const copyShare = async () => {
    if (!sharePath) return;
    const url = `${window.location.origin}${sharePath}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy. Select the link and copy it manually.");
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
      setError(e instanceof Error ? e.message : "Could not save the setting.");
    } finally {
      setGroundingBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-[#f1f2f5] dark:bg-[#0f0b18]">
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-ink/40 dark:text-fog/40">
              WhatsApp
            </p>
            <h1 className="mt-1 text-[24px] font-semibold tracking-tight text-ink dark:text-fog">
              Catalog
            </h1>
            <p className="mt-1 max-w-xl text-[13px] text-ink/50 dark:text-fog/50">
              The items the assistant quotes. Prices and stock come from here —
              it never invents them.
            </p>
          </div>
          <button
            onClick={() => setAdding((v) => !v)}
            className="rounded-full bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-[0_1px_0_rgba(255,255,255,0.2)_inset,0_6px_16px_-8px_rgba(61,29,110,0.7)] transition active:translate-y-[2px] active:scale-[0.98]"
          >
            {adding ? "Close" : "Add item"}
          </button>
        </header>

        <WhatsAppSubnav />

        {error && (
          <p
            role="alert"
            className="mb-4 rounded-2xl bg-[#FF4F6E]/10 px-4 py-3 text-[12px] font-medium text-[#C4304B] dark:text-[#FF8FA3]"
          >
            {error}
          </p>
        )}

        {/* Share link */}
        <section className="mb-4 rounded-[28px] border border-ink/[0.06] bg-white p-5 shadow-[0_1px_2px_rgba(20,16,31,0.04),0_14px_30px_-22px_rgba(20,16,31,0.3)] dark:border-fog/[0.08] dark:bg-ink">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[13px] font-semibold text-ink dark:text-fog">
                Public catalog link
              </h2>
              <p className="mt-0.5 text-[11.5px] text-ink/45 dark:text-fog/45">
                A read-only page with your active items. Anyone with the link can
                open it; turn it off to revoke access.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {sharePath ? (
                <>
                  <code className="max-w-[46vw] truncate rounded-full bg-fog px-3 py-1.5 text-[11px] text-ink/60 dark:bg-fog/[0.08] dark:text-fog/60">
                    {sharePath}
                  </code>
                  <button
                    onClick={() => void copyShare()}
                    className="rounded-full border border-deep-violet/25 px-3 py-1.5 text-[11px] font-bold text-deep-violet transition hover:bg-deep-violet/10 dark:border-fog/20 dark:text-fog"
                  >
                    {copied ? "Copied" : "Copy"}
                  </button>
                  <button
                    onClick={() => void rotateShare()}
                    disabled={busy === "share"}
                    className="rounded-full px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:text-ink disabled:opacity-40 dark:text-fog/50 dark:hover:text-fog"
                  >
                    Replace
                  </button>
                </>
              ) : null}
              <button
                onClick={() => void toggleShare()}
                disabled={busy === "share"}
                className={`rounded-full px-3 py-1.5 text-[11px] font-bold transition disabled:opacity-40 ${
                  sharePath
                    ? "border border-ink/[0.12] text-ink/60 dark:border-fog/20 dark:text-fog/60"
                    : "bg-deep-violet text-white"
                }`}
              >
                {sharePath ? "Turn off" : "Create link"}
              </button>
            </div>
          </div>
        </section>

        {/* Grounding switch */}
        {channels.length > 0 && (
          <section className="mb-4 flex items-center justify-between gap-4 rounded-[28px] border border-ink/[0.06] bg-white p-5 shadow-[0_1px_2px_rgba(20,16,31,0.04),0_14px_30px_-22px_rgba(20,16,31,0.3)] dark:border-fog/[0.08] dark:bg-ink">
            <div>
              <h2 className="text-[13px] font-semibold text-ink dark:text-fog">
                Ground replies in your Databank
              </h2>
              <p className="mt-0.5 text-[11.5px] text-ink/45 dark:text-fog/45">
                Retrieve the passages that answer each customer message. Off means
                the assistant only uses the business profile summary.
              </p>
            </div>
            <button
              role="switch"
              aria-checked={grounding}
              aria-label="Ground replies in your Databank"
              disabled={groundingBusy}
              onClick={() => void setGroundingForAll(!grounding)}
              className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50 ${
                grounding ? "bg-deep-violet" : "bg-ink/15 dark:bg-fog/20"
              }`}
            >
              <span
                className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow-md transition-transform ${
                  grounding ? "translate-x-[22px]" : "translate-x-0.5"
                }`}
              />
            </button>
          </section>
        )}

        {/* Add form */}
        {adding && (
          <section className="mb-4 rounded-[28px] border border-ink/[0.06] bg-white p-5 shadow-[0_1px_2px_rgba(20,16,31,0.04),0_14px_30px_-22px_rgba(20,16,31,0.3)] dark:border-fog/[0.08] dark:bg-ink">
            <h2 className="mb-3 text-[13px] font-semibold text-ink dark:text-fog">
              New item
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-semibold text-ink/50 dark:text-fog/50">Name</span>
                <input
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="Ethiopia Guji 1kg"
                  className="input-field"
                  autoFocus
                />
              </label>
              <div className="grid grid-cols-[1fr_90px] gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-[11px] font-semibold text-ink/50 dark:text-fog/50">Price</span>
                  <input
                    value={draft.price}
                    onChange={(e) => setDraft({ ...draft, price: e.target.value })}
                    inputMode="decimal"
                    placeholder="85.00"
                    className="input-field"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[11px] font-semibold text-ink/50 dark:text-fog/50">Currency</span>
                  <select
                    value={draft.currency}
                    onChange={(e) => setDraft({ ...draft, currency: e.target.value })}
                    className="input-field"
                  >
                    {CURRENCIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label className="flex flex-col gap-1 sm:col-span-2">
                <span className="text-[11px] font-semibold text-ink/50 dark:text-fog/50">Description</span>
                <input
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  placeholder="Whole bean, roasted weekly"
                  className="input-field"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-semibold text-ink/50 dark:text-fog/50">Image URL</span>
                <input
                  value={draft.image_url}
                  onChange={(e) => setDraft({ ...draft, image_url: e.target.value })}
                  placeholder="https://…"
                  className="input-field"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-semibold text-ink/50 dark:text-fog/50">Product link</span>
                <input
                  value={draft.item_url}
                  onChange={(e) => setDraft({ ...draft, item_url: e.target.value })}
                  placeholder="https://…"
                  className="input-field"
                />
              </label>
            </div>
            <div className="mt-4 flex items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-[12px] text-ink/60 dark:text-fog/60">
                <input
                  type="checkbox"
                  checked={draft.in_stock}
                  onChange={(e) => setDraft({ ...draft, in_stock: e.target.checked })}
                  className="h-4 w-4 rounded text-deep-violet"
                />
                In stock
              </label>
              <button
                onClick={() => void saveItem()}
                disabled={!draft.name.trim() || busy === "add"}
                className="rounded-full bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition disabled:opacity-40 active:translate-y-[2px] active:scale-[0.98]"
              >
                {busy === "add" ? "Saving…" : "Save item"}
              </button>
            </div>
          </section>
        )}

        {/* Items */}
        <section className="rounded-[28px] border border-ink/[0.06] bg-white shadow-[0_1px_2px_rgba(20,16,31,0.04),0_14px_30px_-22px_rgba(20,16,31,0.3)] dark:border-fog/[0.08] dark:bg-ink">
          <div className="flex items-center justify-between border-b border-ink/[0.06] px-5 py-3 dark:border-fog/[0.08]">
            <h2 className="text-[13px] font-semibold text-ink dark:text-fog">
              Items
            </h2>
            <span className="text-[11px] text-ink/40 dark:text-fog/40">
              {activeCount} active · {items.length} total
            </span>
          </div>
          {loading ? (
            <p className="px-5 py-10 text-center text-[12px] text-ink/40 dark:text-fog/40">
              Loading…
            </p>
          ) : items.length === 0 ? (
            <p className="px-5 py-10 text-center text-[12px] text-ink/40 dark:text-fog/40">
              No items yet. Add the first one and the assistant can start quoting it.
            </p>
          ) : (
            <ul className="divide-y divide-ink/[0.05] dark:divide-fog/[0.06]">
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  {item.image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={item.image_url}
                      alt=""
                      className="h-10 w-10 rounded-xl bg-fog object-cover dark:bg-fog/[0.08]"
                      onError={(e) => {
                        e.currentTarget.style.display = "none";
                      }}
                    />
                  ) : (
                    <span className="h-10 w-10 rounded-xl bg-deep-violet/10" aria-hidden="true" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold text-ink dark:text-fog">
                      {item.name}
                      {!item.active && (
                        <span className="ml-2 rounded-full bg-ink/[0.06] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-ink/40 dark:bg-fog/[0.08] dark:text-fog/40">
                          Hidden
                        </span>
                      )}
                    </p>
                    <p className="truncate text-[11.5px] text-ink/45 dark:text-fog/45">
                      {item.price_display ?? "No price"}
                      {item.description ? ` · ${item.description}` : ""}
                    </p>
                  </div>
                  <button
                    onClick={() => void toggle(item, { in_stock: !item.in_stock })}
                    disabled={busy === item.id}
                    className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide transition disabled:opacity-40 ${
                      item.in_stock
                        ? "bg-emerald/10 text-emerald"
                        : "bg-ink/[0.06] text-ink/45 dark:bg-fog/[0.08] dark:text-fog/45"
                    }`}
                  >
                    {item.in_stock ? "In stock" : "Out"}
                  </button>
                  <button
                    onClick={() => void toggle(item, { active: !item.active })}
                    disabled={busy === item.id}
                    className="rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-ink/40 transition hover:text-ink disabled:opacity-40 dark:text-fog/40 dark:hover:text-fog"
                  >
                    {item.active ? "Hide" : "Show"}
                  </button>
                  <button
                    onClick={() => void remove(item)}
                    disabled={busy === item.id}
                    aria-label={`Delete ${item.name}`}
                    className="rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-ink/30 transition hover:text-[#C4304B] disabled:opacity-40"
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
