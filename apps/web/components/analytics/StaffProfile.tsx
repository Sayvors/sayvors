"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import { resolveMediaUrl } from "@/lib/media-url";

/* Employee profile (§33): the person's picture and contact details, the credit
 * the review AI attributed to them, its read of those reviews, and only the
 * reviews that name them.
 *
 * Theme: the analytics/team flat system — --ui-* vars, hairlines, no shadows.
 */

interface Employee {
  id: string;
  listing_id: string;
  name: string;
  aliases: string[];
  active: boolean;
  avatar_url: string | null;
  phone: string | null;
  email: string | null;
  job_title: string | null;
  bio: string | null;
}

interface Stats {
  mentions: number;
  positive: number;
  neutral: number;
  negative: number;
  positive_pct: number | null;
  avg_rating: number | null;
  first_mention_at: string | null;
  last_mention_at: string | null;
}

interface Theme {
  name: string;
  mentions: number;
  positive: number;
  neutral: number;
  negative: number;
}

interface Quote {
  review_id: string;
  quote: string;
  rating: number;
  reviewer_name: string | null;
  review_created_at: string | null;
}

interface Analysis {
  source: string;
  meaning_version: number | null;
  summary: string;
  top_themes: Theme[];
  highlights: Quote[];
  concerns: Quote[];
  needs_human: number;
}

interface ReviewAI {
  intent: string | null;
  subject: string | null;
  problem: string | null;
  asks: string[];
  evidence: string[];
  confidence: number | null;
  needs_human: boolean;
  version: number | null;
}

interface Review {
  review_id: string;
  channel_id: string;
  rating: number;
  sentiment: string;
  review_created_at: string | null;
  matched_name: string | null;
  reviewer_name: string | null;
  reviewer_photo_url: string | null;
  review_text: string | null;
  review_url: string | null;
  ai: ReviewAI | null;
}

interface Profile {
  employee: Employee;
  window_days: number | null;
  stats: Stats;
  analysis: Analysis;
  reviews: Review[];
}

interface ChannelRow {
  id: string;
  platform: string;
  listing_id?: string | null;
  display_name?: string | null;
}

const SENTIMENT_STYLE: Record<string, string> = {
  positive: "bg-emerald-100 text-emerald-700",
  neutral: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
  negative: "bg-red-100 text-red-700",
};

const WINDOWS: { label: string; value: number | null }[] = [
  { label: "All time", value: null },
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
  { label: "12 months", value: 365 },
];

function errText(e: unknown, fallback: string): string {
  if (e instanceof Error) {
    try {
      const parsed = JSON.parse(e.message);
      const detail = parsed?.detail;
      if (typeof detail === "string") return detail;
      if (detail && typeof detail === "object" && typeof detail.message === "string") {
        return detail.message;
      }
    } catch {
      /* not JSON — fall through */
    }
    return e.message.slice(0, 240);
  }
  return fallback;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function Stars({ rating }: { rating: number }) {
  const full = Math.max(0, Math.min(5, Math.round(rating)));
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          aria-hidden
          className={n <= full ? "text-[var(--ui-ink)]" : "text-[var(--ui-line-strong)]"}
        >
          ★
        </span>
      ))}
    </span>
  );
}

function Avatar({
  src,
  name,
  size = "lg",
}: {
  src: string | null;
  name: string;
  size?: "sm" | "lg";
}) {
  const [failed, setFailed] = useState(false);
  const resolved = resolveMediaUrl(src);
  useEffect(() => setFailed(false), [src]);

  const dimension = size === "lg" ? "h-20 w-20 text-[26px]" : "h-9 w-9 text-[13px]";
  return (
    <div
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-[var(--ui-sunken)] font-bold text-[var(--ui-ink)] ${dimension}`}
    >
      {resolved && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- runtime provider/upload URL
        <img
          src={resolved}
          alt=""
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        (name || "?").trim().charAt(0).toUpperCase()
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ui-panel p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">{label}</p>
      <p className="mt-1 text-[22px] font-bold leading-none text-[var(--ui-ink)]">{value}</p>
      {hint && <p className="mt-1.5 text-[11px] text-[var(--ui-ink-2)]">{hint}</p>}
    </div>
  );
}

export default function StaffProfile() {
  const params = useParams<{ id: string }>();
  const id = typeof params?.id === "string" ? params.id : "";

  const [profile, setProfile] = useState<Profile | null>(null);
  const [branches, setBranches] = useState<{ id: string; name: string }[]>([]);
  const [days, setDays] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const avatarInput = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState({
    name: "",
    job_title: "",
    phone: "",
    email: "",
    bio: "",
  });

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const query = days === null ? "" : `?days=${days}`;
      const [prof, chans] = await Promise.all([
        apiFetch(`/api/v1/staff/${id}${query}`),
        // Branch names are a nicety: a viewer without channels.view must still
        // see the profile, with the raw listing id as the label.
        apiFetch("/api/v1/channels?limit=100").catch(() => ({ channels: [] })),
      ]);
      setProfile(prof as Profile);
      const google = ((chans as { channels?: ChannelRow[] }).channels ?? []).filter(
        (c) => c.platform === "google_reviews",
      );
      setBranches(
        google.map((c) => ({ id: c.listing_id ?? c.id, name: c.display_name ?? "Branch" })),
      );
    } catch (e) {
      setError(errText(e, "Could not load this employee's profile."));
    } finally {
      setLoading(false);
    }
  }, [id, days]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!profile) return;
    setForm({
      name: profile.employee.name,
      job_title: profile.employee.job_title ?? "",
      phone: profile.employee.phone ?? "",
      email: profile.employee.email ?? "",
      bio: profile.employee.bio ?? "",
    });
  }, [profile]);

  const branchName = useMemo(() => {
    return (listingId: string) =>
      branches.find((b) => b.id === listingId)?.name ?? listingId;
  }, [branches]);

  const save = async () => {
    if (!profile) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await apiFetch(`/api/v1/staff/${profile.employee.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: form.name.trim(),
          job_title: form.job_title.trim(),
          phone: form.phone.trim(),
          email: form.email.trim(),
          bio: form.bio.trim(),
        }),
      });
      setProfile({ ...profile, employee: { ...profile.employee, ...updated } });
      setEditing(false);
      setNotice("Profile saved.");
    } catch (e) {
      setError(errText(e, "Could not save the profile."));
    } finally {
      setBusy(false);
    }
  };

  const uploadAvatar = async (file: File | undefined) => {
    if (!file || !profile) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const updated = await apiFetch(`/api/v1/staff/${profile.employee.id}/avatar`, {
        method: "POST",
        body,
      });
      setProfile({ ...profile, employee: { ...profile.employee, ...updated } });
      setNotice("Photo updated.");
    } catch (e) {
      setError(errText(e, "Could not upload the photo."));
    } finally {
      setBusy(false);
      if (avatarInput.current) avatarInput.current.value = "";
    }
  };

  const removeAvatar = async () => {
    if (!profile) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/staff/${profile.employee.id}/avatar`, { method: "DELETE" });
      setProfile({
        ...profile,
        employee: { ...profile.employee, avatar_url: null },
      });
      setNotice("Photo removed.");
    } catch (e) {
      setError(errText(e, "Could not remove the photo."));
    } finally {
      setBusy(false);
    }
  };

  if (loading && !profile) {
    return <p className="py-10 text-center text-[13px] text-[var(--ui-ink-2)]">Loading profile…</p>;
  }

  if (error && !profile) {
    return (
      <div className="p-4 sm:p-6">
        <p role="alert" className="rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] px-4 py-3 text-[13px] font-semibold text-[var(--ui-ink)]">
          {error}
        </p>
        <Link href="/dashboard/analytics?tab=staff" className="mt-3 inline-block text-[12px] font-semibold text-[var(--ui-ink-2)] underline">
          ← Back to staff
        </Link>
      </div>
    );
  }

  if (!profile) return null;

  const { employee, stats, analysis, reviews } = profile;
  const ratingLabel = stats.avg_rating === null ? "—" : stats.avg_rating.toFixed(1);
  const positivePct = stats.positive_pct === null ? "—" : `${Math.round(stats.positive_pct)}%`;

  return (
    <div className="team-ui h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            href="/dashboard/analytics?tab=staff"
            className="text-[12px] font-semibold text-[var(--ui-ink-2)] transition hover:text-[var(--ui-ink)]"
          >
            ← Back to staff
          </Link>
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="ui-btn bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-bold text-[var(--ui-ink)]"
          >
            {editing ? "Close editor" : "Edit profile"}
          </button>
        </div>

        {notice && (
          <p role="status" className="rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-2 text-[12px] font-medium text-[var(--ui-ink)]">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] px-3 py-2 text-[12px] font-bold text-[var(--ui-ink)]">
            {error}
          </p>
        )}

        {/* Identity */}
        <section className="ui-panel p-5 sm:p-6">
          <div className="flex flex-wrap items-start gap-4">
            <Avatar src={employee.avatar_url} name={employee.name} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-[22px] font-bold leading-tight text-[var(--ui-ink)]">{employee.name}</h1>
                {employee.job_title && (
                  <span className="ui-chip px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink)]">
                    {employee.job_title}
                  </span>
                )}
                {!employee.active && (
                  <span className="ui-chip px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    Inactive
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                {branchName(employee.listing_id)}
              </p>
              {employee.aliases.length > 0 && (
                <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
                  Also known as {employee.aliases.join(", ")}
                </p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[12px] text-[var(--ui-ink)]">
                <span>
                  <span className="text-[var(--ui-ink-2)]">Phone: </span>
                  {employee.phone ? (
                    <a href={`tel:${employee.phone}`} className="font-semibold underline-offset-2 hover:underline">
                      {employee.phone}
                    </a>
                  ) : (
                    <span className="text-[var(--ui-ink-2)]">Not added</span>
                  )}
                </span>
                <span className="min-w-0">
                  <span className="text-[var(--ui-ink-2)]">Email: </span>
                  {employee.email ? (
                    <a href={`mailto:${employee.email}`} className="break-all font-semibold underline-offset-2 hover:underline">
                      {employee.email}
                    </a>
                  ) : (
                    <span className="text-[var(--ui-ink-2)]">Not added</span>
                  )}
                </span>
              </div>
              {employee.bio && (
                <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-[var(--ui-ink)]">{employee.bio}</p>
              )}
            </div>
            <div className="flex shrink-0 flex-col items-end gap-2">
              <div className="text-right">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">Credit rating</p>
                <p className="mt-0.5 flex items-center justify-end gap-2 text-[24px] font-bold leading-none text-[var(--ui-ink)]">
                  {ratingLabel}
                  {stats.avg_rating !== null && <span className="text-[12px] text-[var(--ui-ink-2)]">/ 5</span>}
                </p>
                {stats.avg_rating !== null && (
                  <div className="mt-1 flex justify-end">
                    <Stars rating={stats.avg_rating} />
                  </div>
                )}
              </div>
              <label className="ui-btn cursor-pointer bg-[var(--ui-surface)] px-3 py-1.5 text-center text-[11px] font-bold text-[var(--ui-ink)]">
                {employee.avatar_url ? "Change photo" : "Add photo"}
                <input
                  ref={avatarInput}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  className="sr-only"
                  disabled={busy}
                  onChange={(e) => void uploadAvatar(e.target.files?.[0])}
                />
              </label>
              {employee.avatar_url && (
                <button
                  type="button"
                  onClick={() => void removeAvatar()}
                  disabled={busy}
                  className="text-[11px] font-semibold text-[var(--ui-ink-2)] underline-offset-2 hover:underline disabled:opacity-50"
                >
                  Remove photo
                </button>
              )}
            </div>
          </div>
        </section>

        {editing && (
          <section className="ui-panel p-5 sm:p-6" aria-label="Edit employee profile">
            <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">Edit profile</h2>
            <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
              Contact details are only visible to your team. The photo is public to anyone with the link.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Name</span>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="ui-input w-full bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Job title</span>
                <input
                  value={form.job_title}
                  onChange={(e) => setForm({ ...form, job_title: e.target.value })}
                  placeholder="e.g. Shift lead"
                  className="ui-input w-full bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Phone</span>
                <input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  placeholder="+1 555 0100"
                  className="ui-input w-full bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Email</span>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="name@example.com"
                  className="ui-input w-full bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none"
                />
              </label>
            </div>
            <label className="mt-3 block">
              <span className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Short bio</span>
              <textarea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
                rows={3}
                maxLength={2000}
                placeholder="What are they known for?"
                className="ui-input w-full resize-y bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none"
              />
            </label>
            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void save()}
                disabled={busy || !form.name.trim()}
                className="ui-btn bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-bold text-[var(--ui-on-ink)] disabled:opacity-50"
              >
                {busy ? "Saving…" : "Save profile"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="ui-btn bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)]"
              >
                Cancel
              </button>
            </div>
          </section>
        )}

        {/* Credit stats */}
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Employee credit">
          <Stat
            label="Avg rating"
            value={ratingLabel}
            hint={`${stats.mentions} review${stats.mentions === 1 ? "" : "s"} name them`}
          />
          <Stat label="Mentions" value={String(stats.mentions)} hint="Reviews that credit them" />
          <Stat
            label="Positive"
            value={positivePct}
            hint={`${stats.positive} positive · ${stats.neutral} neutral · ${stats.negative} negative`}
          />
          <Stat
            label="Last mentioned"
            value={stats.last_mention_at ? fmtDate(stats.last_mention_at) : "—"}
            hint={stats.first_mention_at ? `First ${fmtDate(stats.first_mention_at)}` : undefined}
          />
        </section>

        {/* AI analysis */}
        <section className="ui-panel p-5 sm:p-6" aria-label="AI review analysis">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[15px] font-bold text-[var(--ui-ink)]">AI review analysis</h2>
            <span className="ui-chip px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
              From per-review AI{analysis.meaning_version ? ` · v${analysis.meaning_version}` : ""}
            </span>
          </div>
          <p className="mt-2 text-[13px] leading-relaxed text-[var(--ui-ink)]">{analysis.summary}</p>

          {stats.mentions > 0 && (
            <div className="mt-4">
              <div className="flex h-2 w-full overflow-hidden rounded-[8px] bg-[var(--ui-sunken)]" aria-hidden>
                <div className="bg-emerald-500" style={{ width: `${(stats.positive / stats.mentions) * 100}%` }} />
                <div className="bg-[var(--ui-line-strong)]" style={{ width: `${(stats.neutral / stats.mentions) * 100}%` }} />
                <div className="bg-red-500" style={{ width: `${(stats.negative / stats.mentions) * 100}%` }} />
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--ui-ink-2)]">
                <span><span className="font-bold text-emerald-600">{stats.positive}</span> positive</span>
                <span><span className="font-bold text-[var(--ui-ink)]">{stats.neutral}</span> neutral</span>
                <span><span className="font-bold text-red-600">{stats.negative}</span> negative</span>
              </div>
            </div>
          )}

          {analysis.top_themes.length > 0 && (
            <div className="mt-4">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
                What customers mention
              </h3>
              <ul className="mt-2 flex flex-wrap gap-2">
                {analysis.top_themes.map((theme) => (
                  <li key={theme.name} className="ui-chip px-2.5 py-1 text-[11px] text-[var(--ui-ink)]">
                    <span className="font-semibold">{theme.name}</span>
                    <span className="ml-1.5 text-[var(--ui-ink-2)]">×{theme.mentions}</span>
                    {theme.negative > 0 && <span className="ml-1 text-red-600">−{theme.negative}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.needs_human > 0 && (
            <p className="mt-3 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-2 text-[11px] text-[var(--ui-ink-2)]">
              {analysis.needs_human} review{analysis.needs_human === 1 ? "" : "s"} need a person to confirm what the AI understood. Those reviews are marked below.
            </p>
          )}

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Praise</h3>
              {analysis.highlights.length === 0 ? (
                <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">No positive quotes yet.</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {analysis.highlights.map((q) => (
                    <li key={q.review_id} className="rounded-[8px] border border-[var(--ui-line)] p-3">
                      <p className="text-[12px] leading-relaxed text-[var(--ui-ink)]">“{q.quote}”</p>
                      <p className="mt-1.5 text-[10px] text-[var(--ui-ink-2)]">
                        ★{q.rating} · {q.reviewer_name || "Customer"} · {fmtDate(q.review_created_at)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-red-700">Needs attention</h3>
              {analysis.concerns.length === 0 ? (
                <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">No negative quotes.</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {analysis.concerns.map((q) => (
                    <li key={q.review_id} className="rounded-[8px] border border-[var(--ui-line)] p-3">
                      <p className="text-[12px] leading-relaxed text-[var(--ui-ink)]">“{q.quote}”</p>
                      <p className="mt-1.5 text-[10px] text-[var(--ui-ink-2)]">
                        ★{q.rating} · {q.reviewer_name || "Customer"} · {fmtDate(q.review_created_at)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>

        {/* Credited reviews */}
        <section className="space-y-3" aria-label="Reviews that credit this employee">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-[15px] font-bold text-[var(--ui-ink)]">Reviews that credit {employee.name}</h2>
              <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                Only reviews where a customer named them. {profile.window_days === null ? "All time" : `Last ${profile.window_days} days`}.
              </p>
            </div>
            <div className="flex gap-1 rounded-[8px] bg-[var(--ui-sunken)] p-1" role="tablist" aria-label="Review window">
              {WINDOWS.map((w) => {
                const active = w.value === days;
                return (
                  <button
                    key={w.label}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setDays(w.value)}
                    className={`rounded-[8px] px-2.5 py-1 text-[11px] font-semibold transition ${
                      active
                        ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                        : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
                    }`}
                  >
                    {w.label}
                  </button>
                );
              })}
            </div>
          </div>

          {reviews.length === 0 ? (
            <p className="ui-panel px-4 py-8 text-center text-[13px] text-[var(--ui-ink-2)]">
              No reviews mention {employee.name} in this window. Run “Link past reviews” on the Staff tab to import older ones.
            </p>
          ) : (
            <ul className="space-y-2">
              {reviews.map((review) => (
                <li key={`${review.channel_id}-${review.review_id}`} className="ui-panel p-4">
                  <div className="flex items-start gap-3">
                    <Avatar src={review.reviewer_photo_url} name={review.reviewer_name || "Customer"} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="text-[13px] font-bold text-[var(--ui-ink)]">
                          {review.reviewer_name || "A customer"}
                        </span>
                        <span className="text-[12px]">
                          <Stars rating={review.rating} />
                        </span>
                        <span className="text-[11px] text-[var(--ui-ink-2)]">{fmtDate(review.review_created_at)}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${SENTIMENT_STYLE[review.sentiment] ?? SENTIMENT_STYLE.neutral}`}>
                          {review.sentiment}
                        </span>
                        {review.matched_name && (
                          <span className="ui-chip px-2 py-0.5 text-[10px] font-semibold text-[var(--ui-ink-2)]">
                            named “{review.matched_name}”
                          </span>
                        )}
                      </div>
                      {review.review_text && (
                        <p className="mt-2 text-[13px] leading-relaxed text-[var(--ui-ink)]">{review.review_text}</p>
                      )}
                      {review.ai && (
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--ui-ink-2)]">
                          {review.ai.intent && <span>AI intent: <span className="font-semibold text-[var(--ui-ink)]">{review.ai.intent}</span></span>}
                          {review.ai.problem && <span>AI problem: <span className="font-semibold text-[var(--ui-ink)]">{review.ai.problem}</span></span>}
                          {review.ai.needs_human && (
                            <span className="font-semibold text-[var(--ui-ink)]">Needs a human check</span>
                          )}
                        </div>
                      )}
                      {review.ai && review.ai.evidence.length > 0 && (
                        <p className="mt-1 text-[11px] italic text-[var(--ui-ink-2)]">
                          Evidence: “{review.ai.evidence.join(" · ")}”
                        </p>
                      )}
                      {review.review_url && (
                        <a
                          href={review.review_url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-block text-[11px] font-semibold text-[var(--ui-ink)] underline underline-offset-2"
                        >
                          View on Google
                        </a>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}