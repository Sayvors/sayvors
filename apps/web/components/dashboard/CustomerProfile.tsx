"use client";

import Link from "next/link";
import { useState } from "react";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import CustomerAvatar from "@/components/customers/CustomerAvatar";
import { leadCategoryLabelKnown } from "@/lib/lead-labels";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { updateCustomerCategory } from "@/lib/api-customers";
import { resolveMediaUrl } from "@/lib/media-url";
import type { Customer, CustomerProfile as CustomerProfileData } from "@/lib/api-customers";

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";

const PRIORITY_CHIP: Record<string, string> = {
  urgent: "bg-[#FF4F6E]/10 text-[#C4304B]",
  high: "bg-amber-500/10 text-amber-700",
  normal: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  low: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

function isGoogle(platform: string | null): boolean {
  return platform === "google_reviews" || platform === "google";
}

/** Never render the synthetic `google:<digest>` thread key as a phone number. */
function displayPhone(phone: string | null): string | null {
  if (!phone || phone.startsWith("google:")) return null;
  return phone.startsWith("+") ? phone : `+${phone}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-2">
      <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
        {label}
      </p>
      <p className={`mt-0.5 truncate text-[14px] font-bold capitalize tabular-nums ${INK}`}>
        {value}
      </p>
    </div>
  );
}

export default function CustomerProfile({
  profile,
  selected,
  onCategoryChanged,
}: {
  profile: CustomerProfileData;
  selected: Customer;
  onCategoryChanged?: () => void;
}) {
  const { t, locale } = useI18n();
  const u = t.dashboard.customers;
  const catLabel = (value: string | null | undefined): string => {
    if (!value) return "—";
    const lead = leadCategoryLabelKnown(value, locale);
    if (lead) return lead;
    return (u.threadCats as Record<string, string>)[value] ?? value;
  };
  const prioLabel = (value: string | null | undefined): string => {
    if (!value) return "—";
    return (u.priorities as Record<string, string>)[value] ?? value;
  };
  const stageLabel = (value: string | null | undefined): string => {
    if (!value) return "—";
    const stages: Record<string, string> = {
      new: u.stages.new,
      qualified: u.stages.qualified,
      follow_up: u.stages.followUp,
      converted: u.stages.converted,
      lost: u.stages.lost,
    };
    return stages[value] ?? value;
  };
  const fill = (s: string, vars: Record<string, string | number>): string =>
    Object.entries(vars).reduce((out, [k, v]) => out.replaceAll(`{${k}}`, String(v)), s);
  const fmtDate = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleDateString(locale === "ar" ? "ar-SA" : "en-US") : "";
  const fmtDateTime = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleString(locale === "ar" ? "ar-SA" : "en-US") : "";
  const [editing, setEditing] = useState(false);
  const [cat, setCat] = useState(profile.category || "normal");
  const [prio, setPrio] = useState(profile.priority || "normal");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [photoOpen, setPhotoOpen] = useState(false);

  const google = isGoogle(profile.identity.platform);
  const name = profile.identity.name || selected.display_name || u.unknownSender;
  const phone = displayPhone(profile.identity.contact_phone);
  const status = profile.category || "normal";
  const priority = profile.priority || "normal";

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await updateCustomerCategory(selected.channel_id, selected.key, cat, prio);
      onCategoryChanged?.();
      setEditing(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : u.saveFailed);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Identity */}
      <section className="flex items-start gap-3">
        {profile.identity.avatar_url ? (
          <button
            type="button"
            onClick={() => setPhotoOpen(true)}
            aria-label={fill(u.viewPic, { name })}
            className="cursor-zoom-in rounded-full outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 hover:opacity-90"
          >
            <CustomerAvatar name={name} url={profile.identity.avatar_url} size="lg" />
          </button>
        ) : (
          <CustomerAvatar name={name} url={profile.identity.avatar_url} size="lg" />
        )}
        <div className="min-w-0 flex-1">
          <h2 className={`truncate text-[17px] font-bold ${INK}`}>{name}</h2>
          <div className={`mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] ${INK2}`}>
            <span className="inline-flex items-center gap-1.5">
              <PlatformMark platform={profile.identity.platform as never} size={14} />
              {platformLabel(profile.identity.platform ?? "")}
            </span>
            {profile.identity.channel_name && (
              <span className="min-w-0 max-w-full truncate">{profile.identity.channel_name}</span>
            )}
          </div>
          <p className={`mt-1 truncate text-[11px] ${INK2}`}>
            {google
              ? u.googleReviewer
              : profile.identity.username
                ? `@${profile.identity.username}`
                : phone ?? u.noDetails}
          </p>
        </div>
      </section>

      {/* At a glance */}
      <section className="grid grid-cols-3 gap-2">
        <Stat label={u.statMessages} value={String(profile.messages.length)} />
        <Stat label={u.statReviews} value={String(profile.reviews.length)} />
        <Stat label={u.statLead} value={stageLabel(profile.lead?.stage ?? null)} />
      </section>

      {/* Categorization */}
      <section className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
            {u.catTitle}
          </h3>
          <button
            type="button"
            onClick={() => {
              setEditing((v) => !v);
              setSaveError(null);
            }}
            className="text-[11px] font-semibold text-[var(--ui-ink-2)] transition hover:text-[var(--ui-ink)]"
          >
            {editing ? t.common.cancel : u.edit}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
            {catLabel(status)}
          </span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${PRIORITY_CHIP[priority]}`}>
            {prioLabel(priority)}
          </span>
          {profile.important && (
            <span className="rounded-full bg-[#FF4F6E]/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#C4304B]">
              {u.important}
            </span>
          )}
          {!profile.can_reply && (
            <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
              {google ? u.readOnlyGoogle : u.noReplyFromHere}
            </span>
          )}
        </div>
        {editing && (
          <div className="mt-3 space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className={`mb-1 block text-[10px] font-bold uppercase tracking-wide ${INK2}`}>
                  {u.categoryLabel}
                </span>
                <select
                  value={cat}
                  onChange={(e) => setCat(e.target.value)}
                  className="input-field h-9 w-full text-[11px]"
                >
                  <option value="complaint">{u.threadCats.complaint}</option>
                  <option value="feedback">{u.threadCats.feedback}</option>
                  <option value="inquiry">{u.threadCats.inquiry}</option>
                  <option value="review">{u.threadCats.review}</option>
                  <option value="other">{u.threadCats.other}</option>
                  <option value="normal">{u.threadCats.normal}</option>
                </select>
              </label>
              <label className="block">
                <span className={`mb-1 block text-[10px] font-bold uppercase tracking-wide ${INK2}`}>
                  {u.priorityLabel}
                </span>
                <select
                  value={prio}
                  onChange={(e) => setPrio(e.target.value)}
                  className="input-field h-9 w-full text-[11px]"
                >
                  <option value="urgent">{u.priorities.urgent}</option>
                  <option value="high">{u.priorities.high}</option>
                  <option value="normal">{u.priorities.normal}</option>
                  <option value="low">{u.priorities.low}</option>
                </select>
              </label>
            </div>
            {saveError && (
              <p role="alert" className="text-[11px] font-semibold text-[#C4304B]">
                {saveError}
              </p>
            )}
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="h-9 w-full rounded-lg bg-[var(--ui-ink)] text-[11px] font-semibold text-[var(--ui-on-ink)] transition active:translate-y-px disabled:opacity-50"
            >
              {saving ? u.saving : u.saveChanges}
            </button>
          </div>
        )}
      </section>

      {/* Lead */}
      {profile.lead && (
        <section className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
            {u.leadTitle}
          </h3>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[12px]">
            <dt className={`font-semibold ${INK}`}>{u.stage}</dt>
            <dd>
              <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
                {stageLabel(profile.lead.stage)}
              </span>
            </dd>
            {profile.lead.category && (
              <>
                <dt className={`font-semibold ${INK}`}>{u.type}</dt>
                <dd className={INK2}>{leadCategoryLabelKnown(profile.lead.category, locale) ?? profile.lead.category}</dd>
              </>
            )}
            {profile.lead.request && (
              <>
                <dt className={`font-semibold ${INK}`}>{u.request}</dt>
                <dd className={`break-words ${INK2}`}>{profile.lead.request}</dd>
              </>
            )}
            {profile.lead.summary && (
              <>
                <dt className={`font-semibold ${INK}`}>{u.summary}</dt>
                <dd className={`break-words ${INK2}`}>{profile.lead.summary}</dd>
              </>
            )}
            {profile.lead.phone_number && (
              <>
                <dt className={`font-semibold ${INK}`}>{u.phone}</dt>
                <dd className={`tabular-nums ${INK2}`}>{profile.lead.phone_number}</dd>
              </>
            )}
          </dl>
          {profile.lead.opt_out && (
            <p className="mt-2 rounded-lg bg-[#FF4F6E]/10 px-2 py-1 text-[10px] font-semibold text-[#C4304B]">
              {u.optedOut}
            </p>
          )}
        </section>
      )}

      {/* Reviews (Google) */}
      {profile.reviews.length > 0 && (
        <section>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
              {fill(u.googleReviews, { count: profile.reviews.length })}
            </h3>
            <Link
              href="/dashboard/reviews"
              className="text-[11px] font-semibold text-[var(--ui-ink-2)] transition hover:text-[var(--ui-ink)]"
            >
              {u.manage}
            </Link>
          </div>
          <div className="mt-2 space-y-2">
            {profile.reviews.map((r) => (
              <article
                key={r.id}
                className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="text-[12px] font-bold text-amber-600"
                    aria-label={fill(u.starsOutOf, { rating: r.rating })}
                  >
                    {"★".repeat(r.rating)}
                    <span className="text-[var(--ui-ink-2)] opacity-40">{"☆".repeat(5 - r.rating)}</span>
                  </span>
                  <span className="text-[10px] tabular-nums text-[var(--ui-ink-2)]">
                    {fmtDate(r.created_at)}
                  </span>
                </div>
                {r.review_text ? (
                  <p className={`mt-1.5 whitespace-pre-wrap break-words text-[12px] leading-relaxed ${INK}`}>
                    {r.review_text}
                  </p>
                ) : (
                  <p className={`mt-1.5 text-[11px] italic ${INK2}`}>{u.noReviewText}</p>
                )}
                {r.reply_text && (
                  <div className="mt-2 rounded-lg border-l-2 border-deep-violet/30 bg-[var(--ui-surface)] px-2.5 py-2">
                    <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
                      {u.yourReply}
                    </p>
                    <p className={`mt-0.5 whitespace-pre-wrap break-words text-[12px] leading-relaxed ${INK}`}>
                      {r.reply_text}
                    </p>
                  </div>
                )}
                <p className="mt-2 text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
                  {(u.reviewStatuses as Record<string, string>)[r.status] ?? r.status}
                </p>
              </article>
            ))}
          </div>
        </section>
      )}

      {/* Conversation */}
      <section>
        <h3 className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
          {fill(u.conversation, { count: profile.messages.length })}
        </h3>
        <div className="mt-2 max-h-80 space-y-2 overflow-y-auto pr-1">
          {profile.messages.map((m) => {
            const inbound = m.direction === "inbound";
            return (
              <div
                key={m.id}
                className={`rounded-xl px-3 py-2 text-[12px] ${
                  inbound
                    ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
                    : "bg-deep-violet/[0.06] text-[var(--ui-ink)]"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
                    {inbound ? u.customer : u.you}
                  </span>
                  <span className="text-[9px] tabular-nums text-[var(--ui-ink-2)]">
                    {fmtDateTime(m.created_at)}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed">
                  {m.content || "—"}
                </p>
              </div>
            );
          })}
          {profile.messages.length === 0 && (
            <p className={`text-[12px] ${INK2}`}>{u.noMessages}</p>
          )}
        </div>
      </section>

      {photoOpen && profile.identity.avatar_url && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={fill(u.viewPic, { name })}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/70 p-6"
          onClick={() => setPhotoOpen(false)}
        >
          <button
            type="button"
            onClick={() => setPhotoOpen(false)}
            aria-label={u.closePic}
            className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white text-[20px] font-bold text-ink shadow-lg"
          >
            ×
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={resolveMediaUrl(profile.identity.avatar_url) || profile.identity.avatar_url}
            alt={name}
            className="max-h-[82vh] max-w-[82vw] rounded-2xl object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}
