"use client";

import Link from "next/link";
import type { GrowthCards } from "@/lib/api-analytics";
import { FactSource } from "@/components/analytics/FactSource";
import { GBP_DASHBOARD_URL } from "@/lib/google-links";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type CardsDict = Dict["growth"]["cards"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

function platformLabel(p: string): string {
  const map: Record<string, string> = {
    whatsapp: "WhatsApp",
    instagram: "Instagram",
    facebook: "Messenger",
    google_reviews: "Google",
  };
  return map[p] ?? p.replace(/_/g, " ");
}

function triggerLabel(t: string, gc: CardsDict): string {
  const map: Record<string, string> = {
    manual: gc.trigManual,
    qr: gc.trigQr,
    after_visit: gc.trigAfterVisit,
    campaign: gc.trigCampaign,
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
  googleConnected = false,
}: {
  cards: GrowthCards | null;
  loading: boolean;
  /** Whether a Google Business Profile is connected; gates the GBP link. */
  googleConnected?: boolean;
}) {
  const { t, locale } = useI18n();
  const gc: CardsDict = t.growth.cards;
  const gbp = t.bench.fact.gbp;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
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
  const contactPlatforms = c.by_platform.filter((p) => p.contacts > 0);

  return (
    <div className="space-y-4 sm:space-y-5">
      {/* Funnel */}
      <section aria-label={gc.funnelAria} className="ui-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{gc.funnelTitle}</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">
              {fill(gc.funnelSub, { n: fmt(cards.days) })}
            </p>
          </div>
          <Link
            href="/dashboard/reviews?ask=1"
            className="ui-btn shrink-0 rounded-[2px] bg-[var(--ui-ink)] px-2.5 py-1.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
          >
            {gc.askReviews}
          </Link>
        </div>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <FunnelStep label={gc.stepRequests} value={fmt(f.requests_sent)} sub={gc.sent} />
          <FunnelStep
            label={gc.stepDelivered}
            value={f.delivery_tracked ? fmt(f.delivered) : "-"}
            sub={f.delivery_tracked ? gc.reported : gc.notTracked}
          />
          <FunnelStep
            label={gc.stepClicked}
            value={f.click_tracked ? fmt(f.clicked) : "-"}
            sub={f.click_tracked ? gc.linkOpens : gc.notTracked}
          />
          <FunnelStep label={gc.stepReviews} value={fmt(f.reviews)} sub={gc.received} />
          <FunnelStep
            label={gc.stepAttributed}
            value={fmt(f.reviews_via_request)}
            sub={fill(gc.attrSub, { n: fmt(f.attribution_window_days) })}
          />
          <FunnelStep
            label={gc.stepConversion}
            value={conv === null ? "-" : `${fmt(Math.round(conv * 10) / 10)}%`}
            sub={gc.convSub}
          />
        </div>

        <div className="mt-4 grid gap-4 border-t border-[var(--ui-line)] pt-3 sm:grid-cols-2">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{gc.byChannel}</p>
            {byChannel.length === 0 ? (
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{gc.noRequests}</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {byChannel.map((b) => (
                  <li key={b.channel} className="flex items-center justify-between text-[11px]">
                    <span className="text-[var(--ui-ink)]">{platformLabel(b.channel)}</span>
                    <span className="tabular-nums text-[var(--ui-ink-2)]">{fmt(b.requests)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">{gc.byTrigger}</p>
            {byTrigger.length === 0 ? (
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{gc.noRequests}</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {byTrigger.map((b) => {
                  const pct = f.requests_sent ? Math.round((b.requests / f.requests_sent) * 100) : 0;
                  return (
                    <li key={b.trigger} className="flex items-center gap-2 text-[11px]">
                      <span className="w-24 shrink-0 text-[var(--ui-ink)]">{triggerLabel(b.trigger, gc)}</span>
                      <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                        <span className="absolute inset-y-0 left-0 rounded-full bg-[var(--ui-ink)]" style={{ width: `${Math.max(3, pct)}%` }} />
                      </span>
                      <span className="w-8 shrink-0 text-right tabular-nums text-[var(--ui-ink-2)]">{fmt(b.requests)}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
        <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
          {fill(gc.attrNote, { n: fmt(f.attribution_window_days) })}
          {f.failed > 0 ? ` ${f.failed === 1 ? fill(gc.failedOne, {}) : fill(gc.failedN, { n: fmt(f.failed) })}` : ""}
          {!f.delivery_tracked && !f.click_tracked ? ` ${gc.noTracking}` : ""}
        </p>
        <FactSource
          source={googleConnected ? gc.funnelSource : gc.funnelSourcePlain}
          detail={fill(gc.funnelDetail, { n: fmt(cards.days), m: fmt(f.attribution_window_days) })}
          href={googleConnected ? GBP_DASHBOARD_URL : null}
          linkLabel={gbp}
        />
      </section>

      {/* Contacts + retention */}
      <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
        <section aria-label={gc.contactsAria} className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{gc.contactsTitle}</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">{gc.contactsSub}</p>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-[30px] font-black leading-none tabular-nums text-[var(--ui-ink)]">{fmt(c.new_contacts)}</span>
            <span className="text-[12px] font-semibold text-[var(--ui-ink-2)]">{gc.newWord}</span>
            {c.delta_pct !== null && (
              <span className={`rounded-[2px] px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${c.delta_pct > 0 ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"}`}>
                {c.delta_pct > 0 ? "+" : ""}{fmt(Math.round(c.delta_pct * 10) / 10)}%
              </span>
            )}
          </div>
          {c.new_contacts > 0 && contactPlatforms.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {contactPlatforms.map((p) => (
                <li key={p.platform} className="flex items-center justify-between text-[11px]">
                  <span className="text-[var(--ui-ink)]">{platformLabel(p.platform)}</span>
                  <span className="tabular-nums text-[var(--ui-ink-2)]">{fmt(p.contacts)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-[11px] text-[var(--ui-ink-2)]">{gc.noContacts}</p>
          )}
          <p className="mt-3 text-[10px] text-[var(--ui-ink-2)]">
            {gc.unknownPre} <strong>{gc.unknownWord}</strong> {gc.unknownPost}
          </p>
          <FactSource
            source={gc.rollupSource}
            detail={fill(gc.funnelDetailDays, { n: fmt(cards.days) })}
          />
        </section>

        <section aria-label={gc.retentionAria} className="ui-card p-5">
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{gc.retentionTitle}</h3>
          {cards.retention.available ? (
            <p className="mt-3 text-[12px] text-[var(--ui-ink)]">{gc.cohortOk}</p>
          ) : (
            <>
              <p className="mt-3 text-[12px] font-semibold text-[var(--ui-ink)]">{gc.notConnected}</p>
              <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">
                {cards.retention.reason}
              </p>
              <p className="mt-2 text-[10px] text-[var(--ui-ink-2)]">
                {gc.retentionNote}
              </p>
            </>
          )}
        </section>
      </div>

      {/* Actions */}
      <section aria-label={gc.actionsAria} className="ui-card p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">{gc.actionsTitle}</h3>
            <p className="text-[11px] text-[var(--ui-ink-2)]">{gc.actionsSub}</p>
          </div>
        </div>
        {actions.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{gc.actionsEmpty}</p>
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
                      {gc.startAction}
                    </Link>
                  )}
                </div>
                <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{a.detail}</p>
                {a.expected && <p className="mt-0.5 text-[10px] text-[var(--ui-ink-2)]">{a.expected}</p>}
              </li>
            ))}
          </ul>
        )}
        <FactSource
          source={gc.funnelAnalysis}
          detail={gc.funnelAnalysisDetail}
          href={googleConnected ? GBP_DASHBOARD_URL : null}
          linkLabel={gbp}
        />
      </section>
    </div>
  );
}
