"use client";

import Link from "next/link";
import type { GrowthCards } from "@/lib/api-analytics";

function platformLabel(p: string): string {
  const map: Record<string, string> = {
    whatsapp: "WhatsApp",
    instagram: "Instagram",
    facebook: "Messenger",
    google_reviews: "Google",
  };
  return map[p] ?? p.replace(/_/g, " ");
}

function triggerLabel(t: string): string {
  const map: Record<string, string> = {
    manual: "Manual",
    qr: "In-person QR",
    after_visit: "After visit",
    campaign: "Campaign",
  };
  return map[t] ?? t.replace(/_/g, " ");
}

function FunnelStep({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0 flex-1 rounded-[2px] bg-[var(--ui-sunken)] px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{label}</p>
      <p className="mt-0.5 text-[20px] font-black leading-none tabular-nums text-[var(--ui-ink)]">{value}</p>
      {sub && <p className="mt-1 truncate text-[10px] text-[var(--ui-ink-2)]">{sub}</p>}
    </div>
  );
}

export default function GrowthCardsSection({
  cards,
  loading,
}: {
  cards: GrowthCards | null;
  loading: boolean;
}) {
  if (loading || !cards) {
    return (
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <div className="ui-card h-52 animate-pulse" aria-hidden />
        <div className="ui-card h-52 animate-pulse" aria-hidden />
      </div>
    );
  }

  const f = cards.funnel;
  const c = cards.contacts;
  const conv = f.conversion_rate;
  const byTrigger = f.by_trigger ?? [];
  const byChannel = f.by_channel ?? [];
  const actions = cards.actions ?? [];

  return (
    <div className="space-y-4 sm:space-y-5">
      {/* Funnel */}
      <section aria-label="Review engine funnel" className="ui-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Review engine funnel</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">
              Requests sent in the last {cards.days} days, compared with reviews received in the same window.
            </p>
          </div>
          <Link
            href="/dashboard/reviews?ask=1"
            className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
          >
            Ask for reviews
          </Link>
        </div>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <FunnelStep label="Requests" value={String(f.requests_sent)} sub="sent" />
          <FunnelStep
            label="Delivered"
            value={f.delivery_tracked ? String(f.delivered) : "-"}
            sub={f.delivery_tracked ? "reported" : "not tracked"}
          />
          <FunnelStep
            label="Clicked"
            value={f.click_tracked ? String(f.clicked) : "-"}
            sub={f.click_tracked ? "link opens" : "not tracked"}
          />
          <FunnelStep label="Reviews" value={String(f.reviews)} sub="received in window" />
          <FunnelStep
            label="Conversion"
            value={conv === null ? "-" : `${conv}%`}
            sub="reviews / requests"
          />
        </div>

        <div className="mt-4 grid gap-4 border-t border-[var(--ui-line)] pt-3 sm:grid-cols-2">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">By channel</p>
            {byChannel.length === 0 ? (
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">No requests recorded.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {byChannel.map((b) => (
                  <li key={b.channel} className="flex items-center justify-between text-[11px]">
                    <span className="text-[var(--ui-ink)]">{platformLabel(b.channel)}</span>
                    <span className="tabular-nums text-[var(--ui-ink-2)]">{b.requests}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Ask timing</p>
            {byTrigger.length === 0 ? (
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">No requests recorded.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {byTrigger.map((b) => {
                  const pct = f.requests_sent ? Math.round((b.requests / f.requests_sent) * 100) : 0;
                  return (
                    <li key={b.trigger} className="flex items-center gap-2 text-[11px]">
                      <span className="w-24 shrink-0 text-[var(--ui-ink)]">{triggerLabel(b.trigger)}</span>
                      <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                        <span className="absolute inset-y-0 left-0 rounded-full bg-[var(--ui-ink)]" style={{ width: `${Math.max(3, pct)}%` }} />
                      </span>
                      <span className="w-8 shrink-0 text-right tabular-nums text-[var(--ui-ink-2)]">{b.requests}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
        {!f.delivery_tracked && (
          <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
            Delivery and click tracking are not connected yet. Requests are recorded when the ask is opened; we do not invent the missing stages.
          </p>
        )}
      </section>

      {/* Contacts + retention */}
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <section aria-label="New contacts" className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">New contacts</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">First-time inbound contacts, from the stored daily rollup.</p>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-[30px] font-black leading-none tabular-nums text-[var(--ui-ink)]">{c.new_contacts}</span>
            <span className="text-[12px] font-semibold text-[var(--ui-ink-2)]">new</span>
            {c.delta_pct !== null && (
              <span className={`rounded-[2px] px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${c.delta_pct > 0 ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                {c.delta_pct > 0 ? "+" : ""}{c.delta_pct}%
              </span>
            )}
          </div>
          {c.by_platform.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {c.by_platform.map((p) => (
                <li key={p.platform} className="flex items-center justify-between text-[11px]">
                  <span className="text-[var(--ui-ink)]">{platformLabel(p.platform)}</span>
                  <span className="tabular-nums text-[var(--ui-ink-2)]">{p.contacts}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-[11px] text-[var(--ui-ink-2)]">No new contacts in this period.</p>
          )}
          <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
            Source attribution is <strong>unknown</strong> until booking/CRM data is connected.
          </p>
        </section>

        <section aria-label="Retention" className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Retention cohort</h3>
          {cards.retention.available ? (
            <p className="mt-3 text-[12px] text-[var(--ui-ink)]">Cohort data available.</p>
          ) : (
            <>
              <p className="mt-3 text-[12px] font-semibold text-[var(--ui-ink)]">Not connected</p>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                {cards.retention.reason}
              </p>
              <p className="mt-2 text-[10px] text-[var(--ui-ink-2)]">
                We will not guess a repeat rate from messages. Connect a POS/CRM to unlock 30/60/90-day cohorts.
              </p>
            </>
          )}
        </section>
      </div>

      {/* Actions */}
      <section aria-label="Growth actions" className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Growth actions</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">Next steps derived from the numbers above.</p>
          </div>
        </div>
        {actions.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">Nothing to fix right now. Keep asking at the moment of service.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {actions.map((a, i) => (
              <li key={`${a.kind}-${i}`} className="rounded-[2px] border border-[var(--ui-line)] p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-[2px] bg-[var(--ui-sunken)] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
                    {a.kind.replace(/_/g, " ")}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{a.title}</span>
                  {a.href && (
                    <Link href={a.href} className="shrink-0 text-[11px] font-bold text-[var(--ui-ink)] underline underline-offset-2">
                      Start
                    </Link>
                  )}
                </div>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{a.detail}</p>
                {a.expected && <p className="mt-0.5 text-[10px] text-[var(--ui-ink-2)]">{a.expected}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
