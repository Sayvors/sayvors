"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelCampaign,
  createCampaign,
  duplicateCampaign,
  fetchCampaigns,
  type Campaign,
} from "@/lib/api-analytics";
import { useI18n } from "@/lib/i18n/I18nProvider";

const today = () => new Date().toISOString().slice(0, 10);
const plusDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

export default function CampaignsSection() {
  const { t } = useI18n();
  const copy = t.growth.campaigns;
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["analytics", "campaigns"], queryFn: fetchCampaigns });
  const [name, setName] = useState("");
  const [from, setFrom] = useState(plusDays(1));
  const [to, setTo] = useState(plusDays(5));
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = () => queryClient.invalidateQueries({ queryKey: ["analytics", "campaigns"] });

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await createCampaign({
        name, from_date: from, to_date: to,
        message_template: template.trim() || null,
      });
      setName("");
      setTemplate("");
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function act(id: string, action: "duplicate" | "cancel") {
    setBusy(true);
    setError(null);
    try {
      if (action === "duplicate") await duplicateCampaign(id);
      else await cancelCampaign(id);
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const campaigns: Campaign[] = query.data ?? [];

  return (
    <section className="ui-card p-4 sm:p-5" aria-label={copy.title}>
      <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{copy.title}</h3>
      <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">{copy.subtitle}</p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
          {copy.name}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            className="mt-1 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 py-1.5 text-[12px] normal-case tracking-normal text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          />
        </label>
        <label className="text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
          {copy.from}
          <input type="date" value={from} min={today()} onChange={(e) => setFrom(e.target.value)}
            className="mt-1 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 py-1.5 text-[12px] normal-case text-[var(--ui-ink)]" />
        </label>
        <label className="text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
          {copy.to}
          <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)}
            className="mt-1 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 py-1.5 text-[12px] normal-case text-[var(--ui-ink)]" />
        </label>
        <div className="flex items-end">
          <button type="button" onClick={() => void create()} disabled={busy || !name.trim()}
            className="ui-btn w-full bg-[var(--ui-ink)] px-3 py-2 text-[12px] font-bold text-[var(--ui-on-ink)] disabled:opacity-50">
            {copy.create}
          </button>
        </div>
      </div>
      <label className="mt-3 block text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
        {copy.template}
        <input value={template} onChange={(e) => setTemplate(e.target.value)} maxLength={8000}
          placeholder="Hi {name} - {link}"
          className="mt-1 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 py-1.5 text-[12px] normal-case tracking-normal text-[var(--ui-ink)]" />
      </label>
      {error ? <p className="mt-2 text-[11px] text-red-600">{error}</p> : null}

      <ul className="mt-4 divide-y divide-[var(--ui-line)]">
        {campaigns.length === 0 ? (
          <li className="py-3 text-[11px] text-[var(--ui-ink-2)]">{copy.empty}</li>
        ) : null}
        {campaigns.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] font-semibold text-[var(--ui-ink)]">
                {c.name}
                <span className="ml-2 rounded-full bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[9px] font-bold uppercase text-[var(--ui-ink-2)]">
                  {c.status === "cancelled" ? copy.cancelled : c.status}
                </span>
              </p>
              <p className="text-[10.5px] text-[var(--ui-ink-2)]">{c.from_date} → {c.to_date}</p>
            </div>
            <div className="flex gap-3 text-[11px] text-[var(--ui-ink-2)]">
              <span>{copy.sent}: <strong className="text-[var(--ui-ink)]">{c.sent_count}</strong></span>
              <span>{copy.clicked}: <strong className="text-[var(--ui-ink)]">{c.clicked_count}</strong></span>
              <span>{copy.reviewed}: <strong className="text-[var(--ui-ink)]">{c.reviewed_count}</strong></span>
              <span>{copy.rate}: <strong className="text-[var(--ui-ink)]">{c.conversion_rate ?? 0}%</strong></span>
            </div>
            {c.status !== "cancelled" ? (
              <div className="flex gap-2">
                <button type="button" onClick={() => void act(c.id, "duplicate")} disabled={busy}
                  className="rounded-[2px] border border-[var(--ui-line-strong)] px-2 py-1 text-[10px] font-bold text-[var(--ui-ink)] disabled:opacity-50">
                  {copy.duplicate}
                </button>
                <button type="button" onClick={() => void act(c.id, "cancel")} disabled={busy}
                  className="rounded-[2px] border border-red-400 px-2 py-1 text-[10px] font-bold text-red-600 disabled:opacity-50">
                  {copy.cancel}
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
