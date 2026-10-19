"use client";

import { useEffect, useMemo, useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import LogoLoader from "@/components/LogoLoader";
import { apiFetch } from "@/lib/api-rag";
import { getProfile, updateProfile } from "@/lib/api-profile";
import LeadSettingsSection from "@/components/leads/LeadSettingsSection";
import { disconnectMeta, fetchMetaConnections, type MetaConnection } from "@/lib/api-meta";

interface ChannelCfg {
  channel_id: string;
  enabled: boolean;
  tone: string;
  databank_id: string | null;
  min_rating_auto: number;
  model: string;
  approval_mode?: string;
  edited_review_autopost: boolean;
  custom_instructions?: string | null;
  dialect: string;
  reply_language: string;
  promo_product_mentions: boolean;
  promo_links: boolean;
  promo_only_relevant: boolean;
  promo_max_ctas: number;
  handoff_link_enabled: boolean;
}

interface GoogleChannel {
  id: string;
  display_name: string | null;
  status: string;
}

interface DialectOpt {
  code: string;
  dialect_en: string;
  dialect_ar: string;
  examples: string[];
}

interface ToneOpt {
  code: string;
  label: string;
  description: string;
}

// Fallback if the catalog endpoint is unreachable — mirrors the DB seed.
const FALLBACK_TONES: ToneOpt[] = [
  { code: "friendly", label: "Friendly", description: "warm and casual" },
  { code: "professional", label: "Professional", description: "formal and polished" },
  { code: "apologetic", label: "Apologetic", description: "extra empathetic" },
  { code: "playful", label: "Playful", description: "light and fun" },
];

const COUNTRIES: { code: string; name: string }[] = [
  { code: "SA", name: "Saudi Arabia" },
  { code: "AE", name: "United Arab Emirates" },
  { code: "QA", name: "Qatar" },
  { code: "KW", name: "Kuwait" },
  { code: "BH", name: "Bahrain" },
  { code: "OM", name: "Oman" },
  { code: "EG", name: "Egypt" },
  { code: "JO", name: "Jordan" },
  { code: "LB", name: "Lebanon" },
  { code: "SY", name: "Syria" },
  { code: "IQ", name: "Iraq" },
  { code: "YE", name: "Yemen" },
  { code: "SD", name: "Sudan" },
  { code: "LY", name: "Libya" },
  { code: "TN", name: "Tunisia" },
  { code: "DZ", name: "Algeria" },
  { code: "MA", name: "Morocco" },
  { code: "MR", name: "Mauritania" },
  { code: "PS", name: "Palestine" },
  { code: "US", name: "United States" },
  { code: "GB", name: "United Kingdom" },
  { code: "CA", name: "Canada" },
  { code: "AU", name: "Australia" },
  { code: "FR", name: "France" },
  { code: "DE", name: "Germany" },
  { code: "IN", name: "India" },
  { code: "PK", name: "Pakistan" },
  { code: "TR", name: "Türkiye" },
];

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  facebook: "Facebook",
  instagram: "Instagram",
};

/*
 * Section chrome.
 *
 * Near-square radii, hairline rules and a tracked eyebrow: this is a dense
 * operations page full of numbers and switches, so structure comes from rules
 * and alignment rather than from rounded, floating cards.
 */
function Section({
  title,
  subtitle,
  eyebrow,
  children,
  tone = "default",
}: {
  title: string;
  subtitle: string;
  eyebrow?: string;
  children: React.ReactNode;
  tone?: "default" | "danger";
}) {
  const danger = tone === "danger";
  return (
    <section
      className={`rounded-[3px] border bg-white dark:bg-ink ${
        danger ? "border-red-500/30" : "border-ink/[0.08] dark:border-fog/[0.08]"
      }`}
    >
      <header
        className={`border-b px-5 py-4 ${
          danger ? "border-red-500/20" : "border-ink/[0.06] dark:border-fog/[0.06]"
        }`}
      >
        {eyebrow && (
          <p
            className={`text-[10px] font-bold uppercase tracking-[0.1em] ${
              danger ? "text-red-500" : "text-ink/35 dark:text-fog/35"
            }`}
          >
            {eyebrow}
          </p>
        )}
        <h2
          className={`text-[15px] font-bold ${
            danger ? "text-red-600 dark:text-red-400" : "text-ink dark:text-fog"
          }`}
        >
          {title}
        </h2>
        <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
          {subtitle}
        </p>
      </header>
      <div className="px-5 py-5">{children}</div>
    </section>
  );
}

function Field({
  label,
  hint,
  children,
  varies,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  varies?: boolean;
}) {
  return (
    <div>
      <label className="mb-1.5 flex items-baseline gap-1.5 text-[12px] font-medium text-ink/70 dark:text-fog/70">
        <span>{label}</span>
        {hint && <span className="font-normal text-ink/40 dark:text-fog/40">{hint}</span>}
        {varies ? <VariesBadge /> : null}
      </label>
      {children}
    </div>
  );
}

const controlCls =
  "w-full max-w-md rounded-[2px] border border-ink/[0.10] bg-white px-2.5 py-1.5 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog";

const selectCls = controlCls;

const inputCls = controlCls;

// Tenant's own domain — what the company IS. The AI reads this (plus what
// they sell / don't sell below) to answer "do you sell X?" factually and to
// decline off-topic questions instead of hallucinating.
const BUSINESS_TYPES = [
  "Food & Restaurant",
  "Cafe & Bakery",
  "Retail & Shops",
  "E-commerce",
  "Pharmacy",
  "Bank / Finance",
  "AI / SaaS / Software",
  "Agency",
  "Healthcare & Clinics",
  "Beauty & Salon",
  "Gym & Fitness",
  "Education",
  "Media / Content",
  "Professional Services",
  "Non-profit",
  "Other",
];

const ALL = "__all__";

interface BulkFailed {
  id: string;
  name: string;
  error: string;
}

function VariesBadge() {
  return (
    <span
      title="Different values across branches — saving will overwrite all of them"
      className="ml-1.5 inline-flex items-center rounded-full bg-amber-100 px-1.5 py-px align-middle text-[9px] font-bold uppercase tracking-wide text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
    >
      varies
    </span>
  );
}

export default function SettingsPage() {
  const [channels, setChannels] = useState<GoogleChannel[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [configs, setConfigs] = useState<Record<string, ChannelCfg>>({});
  const [dialects, setDialects] = useState<DialectOpt[]>([]);
  const [country, setCountry] = useState("");
  const [savedCountry, setSavedCountry] = useState<string | null>(null);
  // Business context (account-wide, feeds the AI for replies + post drafts).
  const [bizType, setBizType] = useState("");
  const [bizCustom, setBizCustom] = useState("");
  const [bizSells, setBizSells] = useState("");
  const [bizNoSell, setBizNoSell] = useState("");
  const [bizDesc, setBizDesc] = useState("");
  const [savedBiz, setSavedBiz] = useState({ type: "", sells: "", noSell: "", desc: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [confirmBulk, setConfirmBulk] = useState<null | {
    title: string;
    lines: string[];
    branches: { id: string; name: string }[];
    busy: boolean;
    onConfirm: () => void;
  }>(null);
  const [lastBulkFail, setLastBulkFail] = useState<null | {
    label: string;
    failed: BulkFailed[];
    onRetry: () => void;
  }>(null);

  const isBulk = selectedId === ALL;
  const bulkBranches = isBulk ? channels.map((c) => ({ id: c.id, name: c.display_name || "Location" })) : [];

  // Settings are grouped by what they actually govern. A tenant that only
  // connected WhatsApp has no Google locations at all, so "all branches" is
  // meaningless to them -- the Google tab hides itself instead of showing an
  // empty location picker, and account-wide rules never sit under one.
  const [tab, setTab] = useState<"account" | "google" | "social" | "leads">("account");

  const [tones, setTones] = useState<ToneOpt[]>(FALLBACK_TONES);

  // Per-location form state, reset whenever the branch or its config loads.
  const [tone, setTone] = useState("friendly");
  const [replyLang, setReplyLang] = useState("match");
  const [dialect, setDialect] = useState("auto");
  const [promoProducts, setPromoProducts] = useState(false);
  const [promoLinks, setPromoLinks] = useState(false);
  const [handoffLink, setHandoffLink] = useState(true);
  const [promoRelevant, setPromoRelevant] = useState(true);
  const [promoMax, setPromoMax] = useState(1);
  const [editedAutopost, setEditedAutopost] = useState(false);
  // Danger zone — the destructive end of the disconnect flow. The channels
  // page disconnects without wiping; only here does "delete everything" live.
  const [metaConnections, setMetaConnections] = useState<MetaConnection[]>([]);
  const [dangerBusy, setDangerBusy] = useState<string | null>(null);
  const [dangerTarget, setDangerTarget] = useState<MetaConnection | null>(null);
  const [dangerPhrase, setDangerPhrase] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [chData, diaData, toneData, prof] = await Promise.all([
          apiFetch("/api/v1/channels?limit=100"),
          apiFetch("/api/v1/review-engine/dialects").catch(() => ({})),
          apiFetch("/api/v1/review-engine/tones").catch(() => []),
          getProfile().catch(() => null),
        ]);
        if (cancelled) return;
        const google: GoogleChannel[] = (chData.channels ?? []).filter(
          (c: { platform: string }) => c.platform === "google_reviews"
        );
        setChannels(google);
        if (google.length > 0) setSelectedId((prev) => prev ?? (google.length > 1 ? ALL : google[0].id));
        setDialects(diaData?.dialects ?? diaData ?? []);
        if (Array.isArray(toneData) && toneData.length > 0) setTones(toneData);
        if (prof) {
          setCountry(prof.country ?? "");
          setSavedCountry(prof.country ?? null);
          const pType = prof.business_type ?? "";
          if (pType && !BUSINESS_TYPES.includes(pType)) {
            setBizType("Other");
            setBizCustom(pType);
          } else {
            setBizType(pType);
            setBizCustom("");
          }
          setBizSells(prof.business_sells ?? "");
          setBizNoSell(prof.business_doesnt_sell ?? "");
          setBizDesc(prof.business_description ?? "");
          setSavedBiz({
            type: pType,
            sells: prof.business_sells ?? "",
            noSell: prof.business_doesnt_sell ?? "",
            desc: prof.business_description ?? "",
          });
        }
        const cfgs: Record<string, ChannelCfg> = {};
        await Promise.all(
          google.map(async (c) => {
            try {
              cfgs[c.id] = await apiFetch(`/api/v1/channels/${c.id}/autoreply`);
            } catch {
              /* default config is created server-side on first GET */
            }
          })
        );
        if (!cancelled) setConfigs(cfgs);
      } catch {
        /* backend down — empty state renders */
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchMetaConnections()
      .then((d) => {
        if (!cancelled) setMetaConnections(d.connections ?? []);
      })
      .catch(() => {
        /* backend down — empty danger zone renders */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const deleteMetaConnection = async (c: MetaConnection) => {
    setDangerBusy(c.id);
    try {
      await disconnectMeta(c.provider, { deleteData: true });
      const d = await fetchMetaConnections();
      setMetaConnections(d.connections ?? []);
      setBanner({
        kind: "ok",
        text: `${PROVIDER_LABELS[c.provider] ?? c.provider} disconnected — all its data was deleted.`,
      });
    } catch {
      setBanner({
        kind: "err",
        text: `Could not delete ${PROVIDER_LABELS[c.provider] ?? c.provider} data. Try again.`,
      });
    } finally {
      setDangerBusy(null);
      setDangerTarget(null);
      setDangerPhrase("");
    }
  };

  const cfg = selectedId ? configs[selectedId] : undefined;

  // Seed the form from the selected location. Adjusting during render instead
  // of in an effect: an effect would first paint the previous location's
  // values, so switching branches flashed the old language and tone before
  // correcting itself. React re-runs this before committing the new frame.
  //
  // The key must include the config itself, not just selectedId: the location
  // list resolves before the per-location configs are fetched, so keying on
  // selectedId alone would seed defaults and then never overwrite them when
  // the real config arrived. The config fields are included so a save that
  // clamps a value server-side is reflected back into the form.
  const seedKey = `${selectedId ?? ""}|${cfg ? "1" : "0"}|${cfg?.tone ?? ""}|${
    cfg?.reply_language ?? ""
  }|${cfg?.dialect ?? ""}`;
  const [seededFor, setSeededFor] = useState<string | null>(null);
  if (seededFor !== seedKey) {
    setSeededFor(seedKey);
    if (cfg) {
      setTone(cfg.tone ?? "friendly");
      setReplyLang(cfg.reply_language ?? "match");
      setDialect(cfg.dialect ?? "auto");
      setPromoProducts(!!cfg.promo_product_mentions);
      setPromoLinks(!!cfg.promo_links);
      setPromoRelevant(cfg.promo_only_relevant ?? true);
      setPromoMax(Number.isFinite(cfg.promo_max_ctas) ? cfg.promo_max_ctas : 1);
      setEditedAutopost(!!cfg.edited_review_autopost);
      setHandoffLink(cfg.handoff_link_enabled ?? true);
    } else if (isBulk) {
      setTone("friendly");
      setReplyLang("match");
      setDialect("auto");
      setPromoProducts(false);
      setPromoLinks(false);
      setPromoRelevant(true);
      setPromoMax(1);
      setEditedAutopost(false);
      setHandoffLink(true);
    }
  }

  // Per-field "varies across branches" set for bulk mode.
  const bulkVaries = useMemo(() => {
    const set = new Set<string>();
    if (!isBulk || channels.length < 2) return set;
    const ids = channels.map((c) => c.id);
    const differs = (fn: (id: string) => unknown) => {
      const vals = ids.map((id) => JSON.stringify(fn(id) ?? null));
      return new Set(vals).size > 1;
    };
    if (differs((id) => configs[id]?.tone ?? "friendly")) set.add("tone");
    if (differs((id) => configs[id]?.reply_language ?? "match")) set.add("reply_language");
    if (differs((id) => configs[id]?.dialect ?? "auto")) set.add("dialect");
    if (differs((id) => !!configs[id]?.promo_product_mentions)) set.add("promoProducts");
    if (differs((id) => !!configs[id]?.promo_links)) set.add("promoLinks");
    if (differs((id) => configs[id]?.handoff_link_enabled ?? true)) set.add("handoffLink");
    if (differs((id) => configs[id]?.promo_only_relevant ?? true)) set.add("promoRelevant");
    if (differs((id) => configs[id]?.promo_max_ctas ?? 1)) set.add("promoMax");
    if (differs((id) => !!configs[id]?.edited_review_autopost)) set.add("editedAutopost");
    return set;
  }, [isBulk, channels, configs]);

  const bulk = isBulk ? { branches: bulkBranches, varies: bulkVaries } : null;

  async function saveCfg(patch: Record<string, unknown>, okText: string, key: string) {
    if (!selectedId) return;
    setBusy(key);
    setBanner(null);
    try {
      const updated = await apiFetch(`/api/v1/channels/${selectedId}/autoreply`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setConfigs((prev) => ({ ...prev, [selectedId]: updated as ChannelCfg }));
      setBanner({ kind: "ok", text: okText });
    } catch (e) {
      setBanner({
        kind: "err",
        text: e instanceof Error ? e.message.slice(0, 200) : "Could not save.",
      });
    } finally {
      setBusy(null);
    }
  }

  const showBanner = (kind: "ok" | "err", text: string) =>
    setBanner({ kind, text });

  // ── Bulk fan-out: same patch → every branch, per-branch results ──
  const runBulkCfg = async (
    label: string,
    patch: Record<string, unknown>,
    ids?: string[],
  ): Promise<{ ok: number; failed: BulkFailed[] }> => {
    const targets = (ids ?? bulkBranches.map((b) => b.id)).map((id) => ({
      id,
      name: channels.find((c) => c.id === id)?.display_name ?? id,
    }));
    const failed: BulkFailed[] = [];
    let ok = 0;
    await Promise.all(
      targets.map(async (t) => {
        try {
          const updated = await apiFetch(`/api/v1/channels/${t.id}/autoreply`, {
            method: "PUT",
            body: JSON.stringify(patch),
          });
          setConfigs((prev) => ({ ...prev, [t.id]: updated as ChannelCfg }));
          ok++;
        } catch (e) {
          failed.push({
            id: t.id,
            name: t.name,
            error: e instanceof Error ? e.message.slice(0, 120) : "Failed",
          });
        }
      })
    );
    const total = targets.length;
    if (failed.length === 0) {
      showBanner("ok", `${label} saved to all ${total} branch${total === 1 ? "" : "es"}.`);
    } else {
      showBanner(
        "err",
        `${label} saved to ${ok} of ${total} — failed: ${failed.map((f) => f.name).join(", ")}.`
      );
    }
    return { ok, failed };
  };

  const finishBulkRun = (
    retryLabel: string,
    retryRun: (ids: string[]) => Promise<{ ok: number; failed: BulkFailed[] }>,
    failed: BulkFailed[],
  ) => {
    if (failed.length === 0) {
      setLastBulkFail(null);
      return;
    }
    setLastBulkFail({
      label: retryLabel,
      failed,
      onRetry: () => {
        setLastBulkFail(null);
        void retryRun(failed.map((f) => f.id)).then(({ failed: still }) =>
          finishBulkRun(retryLabel, retryRun, still)
        );
      },
    });
  };

  // Open the bulk confirm sheet; the fan-out runs only on confirm.
  const requestBulkSave = (
    title: string,
    lines: string[],
    run: () => Promise<{ ok: number; failed: BulkFailed[] }>,
    retryLabel: string,
    retryRun: (ids: string[]) => Promise<{ ok: number; failed: BulkFailed[] }>,
  ) => {
    setLastBulkFail(null);
    setConfirmBulk({
      title,
      lines,
      branches: bulkBranches,
      busy: false,
      onConfirm: () => {
        setConfirmBulk((prev) => (prev ? { ...prev, busy: true } : prev));
        void run().then(({ failed }) => {
          setConfirmBulk(null);
          finishBulkRun(retryLabel, retryRun, failed);
        });
      },
    });
  };

  async function saveCountry() {
    setBusy("country");
    setBanner(null);
    try {
      const updated = await updateProfile({ country: country || null });
      setSavedCountry(updated.country ?? null);
      setBanner({ kind: "ok", text: "Country saved. Display only — your Google listings are untouched." });
    } catch (e) {
      setBanner({
        kind: "err",
        text: e instanceof Error ? e.message.slice(0, 200) : "Could not save country.",
      });
    } finally {
      setBusy(null);
    }
  }

  const bizTypeEffective = bizType === "Other" ? bizCustom.trim() : bizType;
  const bizDirty =
    bizTypeEffective !== savedBiz.type ||
    bizSells !== savedBiz.sells ||
    bizNoSell !== savedBiz.noSell ||
    bizDesc !== savedBiz.desc;

  async function saveBizContext() {
    setBusy("bizctx");
    setBanner(null);
    try {
      const updated = await updateProfile({
        business_type: bizTypeEffective || null,
        business_sells: bizSells.trim() || null,
        business_doesnt_sell: bizNoSell.trim() || null,
        business_description: bizDesc.trim() || null,
      });
      const pType = updated.business_type ?? "";
      if (pType && !BUSINESS_TYPES.includes(pType)) {
        setBizType("Other");
        setBizCustom(pType);
      } else {
        setBizType(pType);
        setBizCustom("");
      }
      setBizSells(updated.business_sells ?? "");
      setBizNoSell(updated.business_doesnt_sell ?? "");
      setBizDesc(updated.business_description ?? "");
      setSavedBiz({
        type: pType,
        sells: updated.business_sells ?? "",
        noSell: updated.business_doesnt_sell ?? "",
        desc: updated.business_description ?? "",
      });
      setBanner({ kind: "ok", text: "Business context saved — the AI now answers from these facts." });
    } catch (e) {
      setBanner({
        kind: "err",
        text: e instanceof Error ? e.message.slice(0, 200) : "Could not save business context.",
      });
    } finally {
      setBusy(null);
    }
  }

  const dialectName = (code: string) => {
    if (code === "auto") return "Auto";
    const d = dialects.find((x) => x.code === code);
    return d ? `${d.dialect_ar} · ${d.dialect_en}` : code;
  };
  const langName = replyLang === "en" ? "English" : replyLang === "ar" ? "Arabic" : "match review";
  const countryName = COUNTRIES.find((c) => c.code === savedCountry)?.name ?? savedCountry ?? "unset";
  const selectedName = channels.find((c) => c.id === selectedId)?.display_name ?? "location";

  return (
    <div className="h-full overflow-y-auto">
      {/* Sticky header: the location selector and save state stay reachable
          while scrolling a page this long. */}
      <div className="sticky top-0 z-10 border-b border-ink/[0.06] bg-white/95 px-6 py-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/95">
        <Breadcrumbs items={[{ label: "Settings" }]} />
        <div className="mt-2">
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Settings</h1>
          <p className="mt-0.5 text-[13px] text-ink/50 dark:text-fog/50">
            Everything Sayvors knows about your business, grouped by what it applies to.
          </p>
        </div>

        {/* Domain tabs. The Google tab only appears when a Google Business
            Profile is actually connected -- offering a location picker to a
            tenant who has none is the confusion this replaces. */}
        <nav className="mt-4 flex flex-wrap gap-1" aria-label="Settings sections">
          {(
            [
              { key: "account", label: "Account", count: null },
              {
                key: "google",
                label: "Google locations",
                count: channels.length > 0 ? channels.length : null,
                hide: channels.length === 0,
              },
              {
                key: "social",
                label: "Social channels",
                count: metaConnections.length > 0 ? metaConnections.length : null,
              },
              { key: "leads", label: "Lead automation", count: null },
            ] as const
          )
            .filter((t) => !("hide" in t) || !t.hide)
            .map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                aria-current={tab === t.key ? "page" : undefined}
                className={`rounded-[2px] border px-3 py-1.5 text-[12px] font-semibold transition focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--ui-ink)] ${
                  tab === t.key
                    ? "border-ink/15 bg-ink/[0.06] text-ink dark:border-fog/20 dark:bg-fog/[0.08] dark:text-fog"
                    : "border-transparent text-ink/55 hover:bg-ink/[0.04] dark:text-fog/55 dark:hover:bg-fog/[0.06]"
                }`}
              >
                {t.label}
                {"count" in t && t.count ? (
                  <span className="ml-1.5 tabular-nums opacity-70">{t.count}</span>
                ) : null}
              </button>
            ))}
        </nav>
      </div>

      <div className="mx-auto max-w-4xl space-y-4 px-6 py-6">

      {banner && (
        <div
          role="status"
          className={`flex items-center justify-between gap-3 rounded-[2px] border px-3 py-2 text-[13px] ${
            banner.kind === "ok"
              ? "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-300"
              : "border-red-300 bg-red-50 text-red-600 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"
          }`}
        >
          <span>{banner.text}</span>
          <button
            type="button"
            className="shrink-0 text-[12px] underline underline-offset-2"
            onClick={() => setBanner(null)}
          >
            dismiss
          </button>
        </div>
      )}

      {/* Bulk scope banner — unmissable: buttons and receipts repeat it. Google
          tab only: it describes per-location saves, and lead/account settings
          are account-wide, so leaving it above every tab told people their
          lead cadence was about to be written to two branches. */}
      {tab === "google" && isBulk && channels.length > 0 && (
        <div className="rounded-[2px] border-2 border-amber-300 bg-amber-50 p-3 text-[12.5px] dark:border-amber-500/40 dark:bg-amber-500/[0.08]">
          <p className="font-bold text-amber-800 dark:text-amber-200">
            Editing ALL {channels.length} branches — {channels.map((c) => c.display_name || "Location").join(", ")}
          </p>
          <p className="mt-0.5 text-amber-700/80 dark:text-amber-200/70">
            Every save in this tab applies to each branch listed.
          </p>
        </div>
      )}

      {/* Bulk retry — re-runs the same save for failed branches only */}
      {tab === "google" && lastBulkFail && (
        <div className="flex items-center justify-between gap-3 rounded-[2px] border border-red-200 bg-red-50 p-3 text-[13px] text-red-700">
          <span>
            {lastBulkFail.label} failed on: {lastBulkFail.failed.map((f) => f.name).join(", ")}.
          </span>
          <button
            onClick={lastBulkFail.onRetry}
            className="shrink-0 rounded-[2px] bg-red-600 px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-red-700"
          >
            Retry failed ({lastBulkFail.failed.length})
          </button>
        </div>
      )}

      {/* Bulk confirm sheet — the final guard before a mass edit */}
      {confirmBulk && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm bulk edit"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-[3px] border border-ink/[0.06] bg-white p-5 shadow-2xl dark:border-fog/[0.08] dark:bg-ink">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">
              {confirmBulk.title}
            </h2>
            <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">
              Applies to {confirmBulk.branches.length} branches:{" "}
              {confirmBulk.branches.map((b) => b.name).join(", ")}
            </p>
            <ul className="mt-3 max-h-48 space-y-1.5 overflow-y-auto rounded-[2px] bg-ink/[0.03] p-3 text-[12.5px] text-ink/70 dark:bg-fog/[0.04] dark:text-fog/70">
              {confirmBulk.lines.map((line, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className="text-deep-violet">•</span>
                  <span className="break-words">{line}</span>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirmBulk(null)}
                disabled={confirmBulk.busy}
                className="rounded-[2px] px-3.5 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:text-fog/60 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmBulk.onConfirm}
                disabled={confirmBulk.busy}
                className="rounded-[2px] bg-amber-500 px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-amber-600 disabled:opacity-50"
              >
                {confirmBulk.busy
                  ? "Applying..."
                  : `Apply to ${confirmBulk.branches.length} branch${confirmBulk.branches.length === 1 ? "" : "es"}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16">
          <LogoLoader size={28} />
        </div>
      ) : (
        <>
          {tab === "account" && (
            <>
              <Section
                eyebrow="Applies to every channel"
                title="Country"
                subtitle="Display and defaults only. Your Google listings and channel settings are never modified."
              >
            <Field label="Business country">
              <select value={country} onChange={(e) => setCountry(e.target.value)} disabled={busy !== null} className={selectCls}>
                <option value="">Not set</option>
                {COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <button
              onClick={() => void saveCountry()}
              disabled={busy !== null || country === (savedCountry ?? "")}
              className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {busy === "country" ? "Saving…" : "Save country"}
              </button>
              </Section>

              <Section
                eyebrow="Applies to every channel"
                title="Business context"
                subtitle="What your company is. The AI reads this for every reply and post draft — it answers 'do you sell X?' from these facts and declines off-topic questions instead of guessing."
              >
            <Field label="What do you do?" hint="your domain — restaurant, pharmacy, bank…">
              <select value={bizType} onChange={(e) => setBizType(e.target.value)} disabled={busy !== null} className={selectCls}>
                <option value="">Not set</option>
                {BUSINESS_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            {bizType === "Other" && (
              <Field label="Your domain" hint="free text — e.g. Car Wash, Dental Clinic">
                <input
                  value={bizCustom}
                  onChange={(e) => setBizCustom(e.target.value)}
                  disabled={busy !== null}
                  placeholder="Describe what you do"
                  className={inputCls}
                />
              </Field>
            )}
            <Field label="What do you sell?" hint="one per line or comma-separated — your Services page list is included automatically, add only extras here">
              <textarea
                value={bizSells}
                onChange={(e) => setBizSells(e.target.value)}
                disabled={busy !== null}
                rows={2}
                placeholder="repairs, installations, consultations"
                className={`${inputCls} resize-y`}
              />
            </Field>
            <Field label="What you DON'T sell" hint="the AI will politely decline these instead of inventing them">
              <textarea
                value={bizNoSell}
                onChange={(e) => setBizNoSell(e.target.value)}
                disabled={busy !== null}
                rows={2}
                placeholder="anything outside your trade, e.g. alcohol, tobacco"
                className={`${inputCls} resize-y`}
              />
            </Field>
            <Field label="One-line description" hint="shown to the AI as ground truth about your business">
              <input
                value={bizDesc}
                onChange={(e) => setBizDesc(e.target.value)}
                disabled={busy !== null}
                maxLength={500}
                placeholder="Family-run business in Jeddah, known for fast service and fair prices"
                className={inputCls}
              />
            </Field>
            <button
              onClick={() => void saveBizContext()}
              disabled={busy !== null || !bizDirty}
              className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {busy === "bizctx" ? "Saving…" : "Save business context"}
              </button>
              </Section>
            </>
          )}

          {/* ── Data & privacy (GDPR) ─────────────────────────────── */}
          <Section
            tone="danger"
            eyebrow="Data & privacy"
            title="Your data"
            subtitle="Export everything Sayvors holds about you, or permanently delete your account and all associated data. Deletion cannot be undone."
          >
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-ink/[0.06] bg-white px-4 py-3 dark:border-fog/[0.08] dark:bg-ink">
                <div className="min-w-0">
                  <p className="text-[13px] font-semibold text-ink dark:text-fog">Export my data</p>
                  <p className="text-[11px] text-ink/40 dark:text-fog/40">
                    Download a JSON file with all your channels, messages, leads, reviews, notifications, and usage data.
                  </p>
                </div>
                <button
                  onClick={() => {
                    const a = document.createElement("a");
                    a.href = "/api/v1/account/export";
                    a.download = "sayvors-export.json";
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                  }}
                  className="rounded-[2px] border border-ink/[0.12] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:bg-ink/[0.04] dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                >
                  Download export
                </button>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-red-500/20 bg-red-500/[0.04] px-4 py-3 dark:border-red-500/20 dark:bg-red-500/[0.06]">
                <div className="min-w-0">
                  <p className="text-[13px] font-semibold text-red-600 dark:text-red-400">Delete my account</p>
                  <p className="text-[11px] text-ink/40 dark:text-fog/40">
                    Permanently deletes your account and all data — channels, messages, leads, reviews, notifications. Cannot be undone.
                  </p>
                </div>
                <button
                  onClick={async () => {
                    if (!confirm("This will permanently delete your account and ALL data. This cannot be undone. Are you sure?")) return;
                    try {
                      const res = await fetch("/api/v1/account", { method: "DELETE", credentials: "include" });
                      if (res.ok) {
                        window.location.href = "/login";
                      } else {
                        alert("Deletion failed. Please try again.");
                      }
                    } catch {
                      alert("Deletion failed. Please try again.");
                    }
                  }}
                  className="rounded-[2px] border border-red-500/40 px-3 py-1.5 text-[12px] font-semibold text-red-600 transition hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
                >
                  Delete account
                </button>
              </div>
            </div>
          </Section>

          {/* ── Google Business Profile only ─────────────────────────── */}
          {tab === "google" && (
            <>
              {/* The location picker lives HERE, not in the page header: it
                  only ever governed Google-scoped settings, so putting it up
                  top implied it governed everything. */}
              <div className="flex flex-wrap items-end justify-between gap-3 rounded-[3px] border border-ink/[0.08] bg-white px-5 py-4 dark:border-fog/[0.08] dark:bg-ink">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink/35 dark:text-fog/35">
                    Configuring
                  </p>
                  <p className="mt-1 text-[13px] font-semibold text-ink dark:text-fog">
                    Google Business Profile locations
                  </p>
                </div>
                {channels.length > 0 && (
                  <label className="block text-[11px] font-bold text-ink/55 dark:text-fog/55">
                    Location
                    <select
                      value={selectedId ?? ""}
                      onChange={(e) => {
                        setSelectedId(e.target.value || null);
                        setLastBulkFail(null);
                      }}
                      className="mt-1 block w-64 rounded-[2px] border border-ink/[0.10] bg-white px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                    >
                      {channels.length > 1 && (
                        <option value={ALL}>All locations ({channels.length})</option>
                      )}
                      {channels.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.display_name || "Location"}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            </>
          )}

          {tab === "google" && (selectedId ? (
            <>
              <Section
                eyebrow="How the AI writes"
            title="Language & dialect"
                subtitle={isBulk ? `Replies for all ${bulkBranches.length} branches. Dialect applies to Arabic replies.` : `Replies for ${selectedName}. Dialect applies to Arabic replies.`}
              >
                <div>
                  <p className="mb-1.5 text-[12px] font-medium text-ink/60 dark:text-fog/60">
                    Reply language
                    {bulk?.varies.has("reply_language") ? <VariesBadge /> : null}
                  </p>
                  <div className="space-y-1.5">
                    {[
                      { id: "match", label: "Match the review", hint: "Arabic review → Arabic reply, English → English" },
                      { id: "en", label: "Always English", hint: "Every reply in English" },
                      { id: "ar", label: "Always Arabic", hint: "Every reply in Arabic" },
                    ].map((l) => (
                      <label key={l.id} className="flex cursor-pointer items-start gap-2.5 rounded-[2px] border border-ink/[0.06] px-3 py-2 transition hover:border-deep-violet/25 dark:border-fog/[0.06]">
                        <input
                          type="radio"
                          name="reply-lang"
                          checked={replyLang === l.id}
                          onChange={() => setReplyLang(l.id)}
                          disabled={busy !== null}
                          className="mt-0.5 h-4 w-4 text-deep-violet focus:ring-deep-violet/40"
                        />
                        <span>
                          <span className="block text-[13px] font-semibold text-ink dark:text-fog">{l.label}</span>
                          <span className="block text-[11px] text-ink/45 dark:text-fog/45">{l.hint}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
                <Field label="Arabic dialect" hint="used whenever a reply is written in Arabic" varies={bulk?.varies.has("dialect") ?? false}>
                  <select value={dialect} onChange={(e) => setDialect(e.target.value)} disabled={busy !== null} className={selectCls}>
                    <option value="auto">Auto — match the review</option>
                    {dialects
                      .filter((d) => d.code !== "auto")
                      .map((d) => (
                        <option key={d.code} value={d.code}>
                          {d.dialect_ar} · {d.dialect_en}
                        </option>
                      ))}
                  </select>
                </Field>
                <button
                  onClick={() => {
                    if (!isBulk) {
                      void saveCfg({ reply_language: replyLang, dialect }, "Language saved.", "lang");
                      return;
                    }
                    const patch = { reply_language: replyLang, dialect };
                    requestBulkSave(
                      "Apply language to all branches?",
                      [
                        `Reply language → ${replyLang === "en" ? "Always English" : replyLang === "ar" ? "Always Arabic" : "Match the review"}`,
                        `Dialect → ${dialectName(dialect)}`,
                      ],
                      () => runBulkCfg("Language", patch),
                      "Language",
                      (ids) => runBulkCfg("Language", patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "lang" ? "Saving…" : bulk ? `Apply to ${bulk.branches.length} branches` : "Save language"}
                </button>
              </Section>

              <Section eyebrow="How the AI writes" title="Tone & voice" subtitle={isBulk ? `Personality of replies for all ${bulkBranches.length} branches.` : `Personality of replies for ${selectedName}.`}>
                <Field label="Response tone" varies={bulk?.varies.has("tone") ?? false}>
                  <select value={tone} onChange={(e) => setTone(e.target.value)} disabled={busy !== null} className={selectCls}>
                    {tones.map((t) => (
                      <option key={t.code} value={t.code}>
                        {t.label}{t.description ? ` — ${t.description}` : ""}
                      </option>
                    ))}
                    {!tones.some((t) => t.code === tone) && (
                      <option value={tone}>{tone}</option>
                    )}
                  </select>
                </Field>
                <button
                  onClick={() => {
                    if (!isBulk) {
                      void saveCfg({ tone }, "Tone saved.", "tone");
                      return;
                    }
                    requestBulkSave(
                      "Apply tone to all branches?",
                      [`Tone → ${tone}`],
                      () => runBulkCfg("Tone", { tone }),
                      "Tone",
                      (ids) => runBulkCfg("Tone", { tone }, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "tone" ? "Saving…" : bulk ? `Apply to ${bulk.branches.length} branches` : "Save tone"}
                </button>
              </Section>

              <Section
                eyebrow="Review replies"
            title="Review reply marketing"
                subtitle="Off by default. Promotional content can get replies flagged by Google — enable only what you need."
              >
                {(
                  [
                    ["promoProducts", "promoProducts", "Allow promotional product mentions", "Name your products/services by exact name when relevant."],
                    ["promoLinks", "promoLinks", "Allow promotional links", "Include links, but only URLs from your business data — never invented."],
                    ["promoRelevant", "promoRelevant", "Only promote when relevant to the review", "No unprompted pitching, even when promotion is on."],
                  ] as const
                ).map(([key, varyKey, label, hint]) => {
                  const val = key === "promoProducts" ? promoProducts : key === "promoLinks" ? promoLinks : promoRelevant;
                  const set = key === "promoProducts" ? setPromoProducts : key === "promoLinks" ? setPromoLinks : setPromoRelevant;
                  return (
                    <label key={key} className="flex cursor-pointer items-start gap-2.5">
                      <input
                        type="checkbox"
                        checked={val}
                        onChange={(e) => set(e.target.checked)}
                        disabled={busy !== null}
                        className="mt-0.5 h-4 w-4 rounded text-deep-violet focus:ring-deep-violet/40"
                      />
                      <span>
                        <span className="block text-[13px] font-semibold text-ink dark:text-fog">
                          {label}
                          {bulk?.varies.has(varyKey) ? <VariesBadge /> : null}
                        </span>
                        <span className="block text-[11px] text-ink/45 dark:text-fog/45">{hint}</span>
                      </span>
                    </label>
                  );
                })}
                <Field label="Maximum promotional CTAs per reply" varies={bulk?.varies.has("promoMax") ?? false}>
                  <input
                    type="number"
                    min={0}
                    max={5}
                    value={promoMax}
                    onChange={(e) => setPromoMax(Math.max(0, Math.min(5, Number(e.target.value) || 0)))}
                    disabled={busy !== null}
                    className={`${selectCls} max-w-28`}
                  />
                </Field>
                <button
                  onClick={() => {
                    const patch = {
                      promo_product_mentions: promoProducts,
                      promo_links: promoLinks,
                      promo_only_relevant: promoRelevant,
                      promo_max_ctas: promoMax,
                    };
                    if (!isBulk) {
                      void saveCfg(patch, "Marketing preferences saved.", "marketing");
                      return;
                    }
                    requestBulkSave(
                      "Apply marketing to all branches?",
                      [
                        `Product mentions → ${promoProducts ? "on" : "off"}`,
                        `Links → ${promoLinks ? "on" : "off"}`,
                        `Only when relevant → ${promoRelevant ? "on" : "off"}`,
                        `Max CTAs → ${promoMax}`,
                      ],
                      () => runBulkCfg("Marketing", patch),
                      "Marketing",
                      (ids) => runBulkCfg("Marketing", patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "marketing" ? "Saving…" : bulk ? `Apply to ${bulk.branches.length} branches` : "Save marketing"}
                </button>
              </Section>

              <Section
                eyebrow="Review replies"
            title="Edited reviews"
                subtitle="When a customer edits a review you already answered, a fresh reply is drafted for the new content."
              >
                <label className="flex cursor-pointer items-start gap-2.5">
                  <input
                    type="checkbox"
                    checked={editedAutopost}
                    onChange={(e) => setEditedAutopost(e.target.checked)}
                    disabled={busy !== null}
                    className="mt-0.5 h-4 w-4 rounded text-deep-violet focus:ring-deep-violet/40"
                  />
                  <span>
                    <span className="block text-[13px] font-semibold text-ink dark:text-fog">
                      Auto-post the updated reply
                      {bulk?.varies.has("editedAutopost") ? <VariesBadge /> : null}
                    </span>
                    <span className="block text-[11px] text-ink/45 dark:text-fog/45">
                      Off = the updated reply waits for your approval (default). On = it posts automatically, still respecting your approval mode and minimum rating.
                    </span>
                  </span>
                </label>
                <button
                  onClick={() => {
                    const patch = { edited_review_autopost: editedAutopost };
                    if (!isBulk) {
                      void saveCfg(patch, "Edited-review preference saved.", "editedReview");
                      return;
                    }
                    requestBulkSave(
                      "Apply edited-review preference to all branches?",
                      [`Edited-review replies → ${editedAutopost ? "auto-post" : "wait for approval"}`],
                      () => runBulkCfg("Edited reviews", patch),
                      "editedReview",
                      (ids) => runBulkCfg("Edited reviews", patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "editedReview" ? "Saving…" : bulk ? `Apply to ${bulk.branches.length} branches` : "Save"}
                </button>
              </Section>

              <Section
                eyebrow="Review replies"
                title="WhatsApp recovery link"
                subtitle="When a review needs attention, the public reply offers a WhatsApp link with the customer's ticket code. Pricing and plan questions get a normal WhatsApp sales link instead, without a ticket. Note: this makes your WhatsApp number publicly visible on Google."
              >
                <label className="flex cursor-pointer items-start gap-2.5">
                  <input
                    type="checkbox"
                    checked={handoffLink}
                    onChange={(e) => setHandoffLink(e.target.checked)}
                    disabled={busy !== null}
                    className="mt-0.5 h-4 w-4 rounded text-deep-violet focus:ring-deep-violet/40"
                  />
                  <span>
                    <span className="block text-[13px] font-semibold text-ink dark:text-fog">
                      Offer reviewers the WhatsApp link
                      {bulk?.varies.has("handoffLink") ? <VariesBadge /> : null}
                    </span>
                    <span className="block text-[11px] text-ink/45 dark:text-fog/45">
                      On problem reviews the link carries the ticket code; on pricing/plan questions it opens a normal sales conversation. Off keeps your number off the listing entirely.
                    </span>
                  </span>
                </label>
                <button
                  onClick={() => {
                    const patch = { handoff_link_enabled: handoffLink };
                    if (!isBulk) {
                      void saveCfg(patch, "WhatsApp link preference saved.", "handoffLink");
                      return;
                    }
                    requestBulkSave(
                      "Apply WhatsApp link preference to all branches?",
                      [`Recovery link → ${handoffLink ? "offered" : "hidden"}`],
                      () => runBulkCfg("WhatsApp link", patch),
                      "handoffLink",
                      (ids) => runBulkCfg("WhatsApp link", patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "handoffLink" ? "Saving…" : bulk ? `Apply to ${bulk.branches.length} branches` : "Save"}
                </button>
              </Section>

              <p className="rounded-[2px] border border-ink/[0.06] bg-white/60 px-4 py-3 text-[12px] text-ink/55 dark:border-fog/[0.06] dark:bg-ink/60 dark:text-fog/55">
                Replies in: <strong>{langName}</strong>
                {langName !== "English" && <> ({dialectName(dialect)})</>} · Tone: <strong className="capitalize">{tone}</strong> · Country:{" "}
                <strong>{countryName}</strong> · Promo:{" "}
                <strong>{promoProducts || promoLinks ? `on (max ${promoMax} CTA${promoMax === 1 ? "" : "s"})` : "off"}</strong>
                {" "}· WhatsApp link: <strong>{handoffLink ? "on" : "off"}</strong>
              </p>
            </>
          ) : (
            <div className="rounded-[3px] border border-dashed border-ink/[0.12] bg-white/60 p-10 text-center dark:border-fog/[0.12] dark:bg-ink/60">
              <p className="text-[14px] font-semibold text-ink/70 dark:text-fog/70">
                No Google locations connected
              </p>
              <p className="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-ink/45 dark:text-fog/45">
                Language, tone and review marketing are configured per Google Business Profile
                location. If you only use WhatsApp, Instagram or Facebook you do not need this —
                everything that applies to you is under Social channels and Lead automation.
              </p>
            </div>
          ))}
          </>
          )}

          {/* ── Social channels ───────────────────────────────────────── */}
          {tab === "social" && (
            <Section
              eyebrow="WhatsApp · Instagram · Facebook"
              title="Connected channels"
              subtitle="Messaging channels on this account. Per-channel options — numbering, AI replies, voice, connected pages — live on the Channels page."
            >
              {metaConnections.length === 0 ? (
                <p className="text-[12px] text-ink/45 dark:text-fog/45">
                  No messaging channels connected yet.
                </p>
              ) : (
                <ul className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                  {metaConnections.map((c) => (
                    <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0">
                      <div className="min-w-0">
                        <p className="text-[13px] font-semibold text-ink dark:text-fog">
                          {PROVIDER_LABELS[c.provider] ?? c.provider}
                        </p>
                        <p className="text-[11px] text-ink/40 dark:text-fog/40">
                          Connected {new Date(c.created_at).toLocaleDateString()} · status{" "}
                          {c.status}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          )}

          {/* ── Lead automation ────────────────────────────────────────── */}
          {tab === "leads" && <LeadSettingsSection />}

      {/* Danger zone — the only place a disconnect also deletes data. The
          channels-page dialog intentionally disconnects without wiping.
          Lives under Social channels because it destroys channel data. */}
      {tab === "social" && (
      <Section
        tone="danger"
        eyebrow="Destructive"
        title="Danger zone"
        subtitle="Permanently disconnect a channel and delete everything it stores — conversations, messages, channels and assets. This cannot be undone."
      >
        <div className="space-y-2">
          {metaConnections.length === 0 ? (
            <p className="text-[12px] text-ink/40 dark:text-fog/40">No connected channels.</p>
          ) : (
            metaConnections.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-[2px] border border-ink/[0.06] bg-white px-3 py-2.5 dark:border-fog/[0.08] dark:bg-ink"
              >
                <div className="min-w-0">
                  <p className="text-[13px] font-semibold text-ink dark:text-fog">
                    {PROVIDER_LABELS[c.provider] ?? c.provider}
                    <span className="ml-2 rounded bg-ink/[0.06] px-1.5 py-0.5 text-[10px] font-bold uppercase text-ink/45 dark:bg-fog/[0.08] dark:text-fog/45">
                      {c.status}
                    </span>
                  </p>
                  <p className="text-[11px] text-ink/40 dark:text-fog/40">
                    Connected {new Date(c.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setDangerPhrase("");
                    setDangerTarget(c);
                  }}
                  disabled={dangerBusy !== null}
                  className="rounded-[2px] border border-red-500/40 px-3 py-1.5 text-[12px] font-semibold text-red-600 transition hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
                >
                  Disconnect &amp; delete all data
                </button>
              </div>
            ))
          )}
        </div>
      </Section>
      )}

      {/* ── Data & privacy (GDPR) — merged with danger zone ─────── */}
      <Section
        tone="danger"
        eyebrow="Data & privacy"
        title="Your data"
        subtitle="Export everything Sayvors holds about you, or permanently delete your account and all associated data. Deletion cannot be undone."
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-ink/[0.06] bg-white px-4 py-3 dark:border-fog/[0.08] dark:bg-ink">
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-ink dark:text-fog">Export my data</p>
              <p className="text-[11px] text-ink/40 dark:text-fog/40">
                Download a JSON file with all your channels, messages, leads, reviews, notifications, and usage data.
              </p>
            </div>
            <button
              onClick={() => {
                const a = document.createElement("a");
                a.href = "/api/v1/account/export";
                a.download = "sayvors-export.json";
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
              }}
              className="rounded-[2px] border border-ink/[0.12] bg-white px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:bg-ink/[0.04] dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
            >
              Download export
            </button>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-red-500/20 bg-red-500/[0.04] px-4 py-3 dark:border-red-500/20 dark:bg-red-500/[0.06]">
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-red-600 dark:text-red-400">Delete my account</p>
              <p className="text-[11px] text-ink/40 dark:text-fog/40">
                Permanently deletes your account and all data — channels, messages, leads, reviews, notifications. Cannot be undone.
              </p>
            </div>
            <button
              onClick={async () => {
                if (!confirm("This will permanently delete your account and ALL data. This cannot be undone. Are you sure?")) return;
                try {
                  const res = await fetch("/api/v1/account", { method: "DELETE", credentials: "include" });
                  if (res.ok) {
                    window.location.href = "/login";
                  } else {
                    alert("Deletion failed. Please try again.");
                  }
                } catch {
                  alert("Deletion failed. Please try again.");
                }
              }}
              className="rounded-[2px] border border-red-500/40 px-3 py-1.5 text-[12px] font-semibold text-red-600 transition hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
            >
              Delete account
            </button>
          </div>
        </div>
      </Section>



      {/* Type-to-confirm modal — one wrong glance should not delete a
          tenant's whole history, so the button stays dead until the exact
          phrase is typed. */}
      {dangerTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={(e) => {
            if (e.target === e.currentTarget && dangerBusy === null) {
              setDangerTarget(null);
              setDangerPhrase("");
            }
          }}
        >
          <div className="w-full max-w-md rounded-[3px] border border-red-500/30 bg-white p-5 shadow-xl dark:border-fog/[0.08] dark:bg-ink">
            <p className="text-[15px] font-bold text-red-600 dark:text-red-400">
              Delete all {PROVIDER_LABELS[dangerTarget.provider] ?? dangerTarget.provider} data?
            </p>
            <p className="mt-2 text-[12px] leading-relaxed text-ink/70 dark:text-fog/70">
              This disconnects the channel and permanently deletes every conversation,
              message, channel and asset connected to it.{" "}
              <strong>It cannot be undone.</strong>
            </p>
            <label className="mt-3 block text-[11px] font-semibold text-ink/55 dark:text-fog/55">
              Type <span className="font-mono text-red-600 dark:text-red-400">DELETE MY DATA</span> to
              confirm
              <input
                autoFocus
                value={dangerPhrase}
                onChange={(e) => setDangerPhrase(e.target.value)}
                placeholder="DELETE MY DATA"
                disabled={dangerBusy !== null}
                className="mt-1.5 w-full rounded-[2px] border border-ink/[0.08] bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-red-500/50 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setDangerTarget(null);
                  setDangerPhrase("");
                }}
                disabled={dangerBusy !== null}
                className="rounded-[2px] px-3 py-1.5 text-[12px] font-semibold text-ink/50 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:text-fog/50"
              >
                Cancel
              </button>
              <button
                onClick={() => void deleteMetaConnection(dangerTarget)}
                disabled={dangerPhrase !== "DELETE MY DATA" || dangerBusy !== null}
                className="rounded-[2px] bg-red-600 px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-40"
              >
                {dangerBusy === dangerTarget.id ? "Deleting…" : "Delete everything"}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
