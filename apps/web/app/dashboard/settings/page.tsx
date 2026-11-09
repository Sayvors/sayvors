"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Breadcrumbs from "@/components/Breadcrumbs";
import LogoLoader from "@/components/LogoLoader";
import { apiFetch } from "@/lib/api-rag";
import { getProfile, updateProfile } from "@/lib/api-profile";
import { COUNTRIES } from "@/lib/countries";
import { BUSINESS_TYPES } from "@/lib/business-types";
import LeadSettingsSection from "@/components/leads/LeadSettingsSection";
import { disconnectMeta, fetchMetaConnections, type MetaConnection } from "@/lib/api-meta";
import {
  cancelPersonalDataDeletion,
  fetchDeletionState,
  requestPersonalDataDeletion,
  type DeletionState,
} from "@/lib/api-account";
import { useI18n } from "@/lib/i18n/I18nProvider";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

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
  handoff_code_ttl_days: number;
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
const ALL = "__all__";

interface BulkFailed {
  id: string;
  name: string;
  error: string;
}

function VariesBadge() {
  const { t } = useI18n();
  return (
    <span
      title={t.reviews.settings.variesTitle}
      className="ml-1.5 inline-flex items-center rounded-full bg-amber-100 px-1.5 py-px align-middle text-[9px] font-bold uppercase tracking-wide text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
    >
      {t.reviews.settings.variesChip}
    </span>
  );
}

export default function SettingsPage() {  const queryClient = useQueryClient();
  const { t, locale } = useI18n();
  const st = t.reviews.settings;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
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
  const bulkBranches = isBulk ? channels.map((c) => ({ id: c.id, name: c.display_name || st.locationFallback })) : [];

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
  const [handoffTtlDays, setHandoffTtlDays] = useState(1);
  const [promoRelevant, setPromoRelevant] = useState(true);
  const [promoMax, setPromoMax] = useState(1);
  const [editedAutopost, setEditedAutopost] = useState(false);
  // Danger zone — the destructive end of the disconnect flow. The channels
  // page disconnects without wiping; only here does "delete everything" live.
  const [metaConnections, setMetaConnections] = useState<MetaConnection[]>([]);
  const [dangerBusy, setDangerBusy] = useState<string | null>(null);
  const [dangerTarget, setDangerTarget] = useState<MetaConnection | null>(null);
  const [dangerPhrase, setDangerPhrase] = useState("");
  const [deletion, setDeletion] = useState<DeletionState | null>(null);
  const [deletionBusy, setDeletionBusy] = useState(false);
  const [deletionModal, setDeletionModal] = useState(false);
  const [deletionConfirm, setDeletionConfirm] = useState("");

  useEffect(() => {
    let alive = true;
    fetchDeletionState()
      .then((state) => {
        if (alive) setDeletion(state);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const settingsQuery = useQuery({
    queryKey: ["settings", "all"],
    queryFn: async () => {
      const [chData, diaData, toneData, prof] = await Promise.all([
        apiFetch("/api/v1/channels?limit=100"),
        apiFetch("/api/v1/review-engine/dialects").catch(() => ({})),
        apiFetch("/api/v1/review-engine/tones").catch(() => []),
        getProfile().catch(() => null),
      ]);
      const google: GoogleChannel[] = (chData.channels ?? []).filter(
        (c: { platform: string }) => c.platform === "google_reviews"
      );
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
      return { channels: google, dialects: diaData?.dialects ?? diaData ?? [], tones: Array.isArray(toneData) && toneData.length > 0 ? toneData : null, profile: prof, configs: cfgs };
    },
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    const d = settingsQuery.data;
    if (!d) return;
    setChannels(d.channels);
    if (d.channels.length > 0) setSelectedId((prev) => prev ?? (d.channels.length > 1 ? ALL : d.channels[0].id));
    setDialects(d.dialects);
    if (d.tones) setTones(d.tones);
    if (d.profile) {
      const prof = d.profile;
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
    setConfigs(d.configs);
    setLoading(false);
  }, [settingsQuery.data]);

  useEffect(() => {
    if (settingsQuery.isError) setLoading(false);
  }, [settingsQuery.isError]);

  const metaConnectionsQuery = useQuery({
    queryKey: ["settings", "meta-connections"],
    queryFn: async () => {
      const d = await fetchMetaConnections();
      return d.connections ?? [];
    },
    staleTime: 5 * 60 * 1000,
  });
  useEffect(() => {
    const d = metaConnectionsQuery.data;
    if (d) setMetaConnections(d);
  }, [metaConnectionsQuery.data]);

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
      setHandoffTtlDays(cfg.handoff_code_ttl_days ?? 1);
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
      setHandoffTtlDays(1);
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
    if (differs((id) => configs[id]?.handoff_code_ttl_days ?? 1)) set.add("handoffTtl");
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
        text: e instanceof Error ? e.message.slice(0, 200) : st.saveFailedDetail,
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
      targets.map(async (tg) => {
        try {
          const updated = await apiFetch(`/api/v1/channels/${tg.id}/autoreply`, {
            method: "PUT",
            body: JSON.stringify(patch),
          });
          setConfigs((prev) => ({ ...prev, [tg.id]: updated as ChannelCfg }));
          ok++;
        } catch (e) {
          failed.push({
            id: tg.id,
            name: tg.name,
            error: e instanceof Error ? e.message.slice(0, 120) : st.itemFailed,
          });
        }
      })
    );
    const total = targets.length;
    if (failed.length === 0) {
      showBanner("ok", total === 1 ? fill(st.savedAllOne, { label }) : fill(st.savedAllN, { label, n: fmt(total) }));
    } else {
      showBanner(
        "err",
        fill(st.savedPartial, { label, ok: fmt(ok), total: fmt(total), names: failed.map((f) => f.name).join(", ") }),
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
      setBanner({ kind: "ok", text: st.account.countrySaved });
    } catch (e) {
      setBanner({
        kind: "err",
        text: e instanceof Error ? e.message.slice(0, 200) : st.account.countryFail,
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
      setBanner({ kind: "ok", text: st.account.ctxSaved });
    } catch (e) {
      setBanner({
        kind: "err",
        text: e instanceof Error ? e.message.slice(0, 200) : st.account.ctxFail,
      });
    } finally {
      setBusy(null);
    }
  }

  const dialectName = (code: string) => {
    if (code === "auto") return st.recap.langAuto;
    const d = dialects.find((x) => x.code === code);
    return d ? `${d.dialect_ar} · ${d.dialect_en}` : code;
  };
  const langName = replyLang === "en" ? st.recap.langEn : replyLang === "ar" ? st.recap.langAr : replyLang === "ur" ? st.recap.langUr : replyLang === "ur-Latn" ? st.recap.langUrLatn : st.recap.langMatch;
  const countryName = COUNTRIES.find((c) => c.code === savedCountry)?.name ?? savedCountry ?? st.unset;
  const selectedName = channels.find((c) => c.id === selectedId)?.display_name ?? st.locationWord;

  return (
    <div className="h-full overflow-y-auto">
      {/* Sticky header: the location selector and save state stay reachable
          while scrolling a page this long. */}
      <div className="sticky top-0 z-10 border-b border-ink/[0.06] bg-white/95 px-6 py-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/95">
        <Breadcrumbs items={[{ label: st.crumbs }]} />
        <div className="mt-2">
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">{st.title}</h1>
          <p className="mt-0.5 text-[13px] text-ink/50 dark:text-fog/50">
            {st.sub}
          </p>
        </div>

        {/* Domain tabs. The Google tab only appears when a Google Business
            Profile is actually connected -- offering a location picker to a
            tenant who has none is the confusion this replaces. */}
        <nav className="mt-4 flex flex-wrap gap-1" aria-label={st.tabs.sectionsAria}>
          {(
            [
              { key: "account", label: st.tabs.account, count: null },
              {
                key: "google",
                label: st.tabs.google,
                count: channels.length > 0 ? channels.length : null,
                hide: channels.length === 0,
              },
              {
                key: "social",
                label: st.tabs.social,
                count: metaConnections.length > 0 ? metaConnections.length : null,
              },
              { key: "leads", label: st.tabs.leads, count: null },
            ] as const
          )
            .filter((tb) => !("hide" in tb) || !tb.hide)
            .map((tb) => (
              <button
                key={tb.key}
                type="button"
                onClick={() => setTab(tb.key)}
                aria-current={tab === tb.key ? "page" : undefined}
                className={`rounded-[2px] border px-3 py-1.5 text-[12px] font-semibold transition focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--ui-ink)] ${
                  tab === tb.key
                    ? "border-ink/15 bg-ink/[0.06] text-ink dark:border-fog/20 dark:bg-fog/[0.08] dark:text-fog"
                    : "border-transparent text-ink/55 hover:bg-ink/[0.04] dark:text-fog/55 dark:hover:bg-fog/[0.06]"
                }`}
              >
                {tb.label}
                {"count" in tb && tb.count ? (
                  <span className="ml-1.5 tabular-nums opacity-70">{fmt(tb.count)}</span>
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
            {st.bannerDismiss}
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
            {fill(st.bulkAll, { n: fmt(channels.length), names: channels.map((c) => c.display_name || st.locationFallback).join(", ") })}
          </p>
          <p className="mt-0.5 text-amber-700/80 dark:text-amber-200/70">
            {st.bulkAllBody}
          </p>
        </div>
      )}

      {/* Bulk retry — re-runs the same save for failed branches only */}
      {tab === "google" && lastBulkFail && (
        <div className="flex items-center justify-between gap-3 rounded-[2px] border border-red-200 bg-red-50 p-3 text-[13px] text-red-700">
          <span>
            {fill(st.bulkFail, { label: lastBulkFail.label, names: lastBulkFail.failed.map((f) => f.name).join(", ") })}
          </span>
          <button
            onClick={lastBulkFail.onRetry}
            className="shrink-0 rounded-[2px] bg-red-600 px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-red-700"
          >
            {fill(st.retryFailed, { n: fmt(lastBulkFail.failed.length) })}
          </button>
        </div>
      )}

      {/* Bulk confirm sheet — the final guard before a mass edit */}
      {confirmBulk && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label={st.confirmTitle}
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-[3px] border border-ink/[0.06] bg-white p-5 shadow-2xl dark:border-fog/[0.08] dark:bg-ink">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">
              {confirmBulk.title}
            </h2>
            <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">
              {fill(st.confirmApplies, { n: fmt(confirmBulk.branches.length), names: confirmBulk.branches.map((b) => b.name).join(", ") })}
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
                {st.cancel}
              </button>
              <button
                onClick={confirmBulk.onConfirm}
                disabled={confirmBulk.busy}
                className="rounded-[2px] bg-amber-500 px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-amber-600 disabled:opacity-50"
              >
                {confirmBulk.busy
                  ? st.applying
                  : confirmBulk.branches.length === 1 ? st.applyOne : fill(st.applyN, { n: fmt(confirmBulk.branches.length) })}
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
                eyebrow={st.account.eyebrow}
                title={st.account.countryTitle}
                subtitle={st.account.countrySub}
              >
            <Field label={st.account.countryLabel}>
              <select value={country} onChange={(e) => setCountry(e.target.value)} disabled={busy !== null} className={selectCls}>
                <option value="">{st.notSet}</option>
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
              {busy === "country" ? st.saving : st.account.saveCountry}
              </button>
              </Section>

              <Section
                eyebrow={st.account.eyebrow}
                title={st.account.ctxTitle}
                subtitle={st.account.ctxSub}
              >
            <Field label={st.account.typeLabel} hint={st.account.typeHint}>
              <select value={bizType} onChange={(e) => setBizType(e.target.value)} disabled={busy !== null} className={selectCls}>
                <option value="">{st.notSet}</option>
                {BUSINESS_TYPES.map((bt) => (
                  <option key={bt} value={bt}>
                    {bt}
                  </option>
                ))}
              </select>
            </Field>
            {bizType === "Other" && (
              <Field label={st.account.customLabel} hint={st.account.customHint}>
                <input
                  value={bizCustom}
                  onChange={(e) => setBizCustom(e.target.value)}
                  disabled={busy !== null}
                  placeholder={st.account.customPh}
                  className={inputCls}
                />
              </Field>
            )}
            <Field label={st.account.sellsLabel} hint={st.account.sellsHint}>
              <textarea
                value={bizSells}
                onChange={(e) => setBizSells(e.target.value)}
                disabled={busy !== null}
                rows={2}
                placeholder={st.account.sellsPh}
                className={`${inputCls} resize-y`}
              />
            </Field>
            <Field label={st.account.noSellLabel} hint={st.account.noSellHint}>
              <textarea
                value={bizNoSell}
                onChange={(e) => setBizNoSell(e.target.value)}
                disabled={busy !== null}
                rows={2}
                placeholder={st.account.noSellPh}
                className={`${inputCls} resize-y`}
              />
            </Field>
            <Field label={st.account.descLabel} hint={st.account.descHint}>
              <input
                value={bizDesc}
                onChange={(e) => setBizDesc(e.target.value)}
                disabled={busy !== null}
                maxLength={500}
                placeholder={st.account.descPh}
                className={inputCls}
              />
            </Field>
            <button
              onClick={() => void saveBizContext()}
              disabled={busy !== null || !bizDirty}
              className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {busy === "bizctx" ? st.saving : st.account.saveCtx}
              </button>
              </Section>
            </>
          )}

          {/* ── Google Business Profile only ─────────────────────────── */}
          {tab === "google" && (
            <>
              {/* The location picker lives HERE, not in the page header: it
                  only ever governed Google-scoped settings, so putting it up
                  top implied it governed everything. */}
              <div className="flex flex-wrap items-end justify-between gap-3 rounded-[3px] border border-ink/[0.08] bg-white px-5 py-4 dark:border-fog/[0.08] dark:bg-ink">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink/35 dark:text-fog/35">
                    {st.configuring}
                  </p>
                  <p className="mt-1 text-[13px] font-semibold text-ink dark:text-fog">
                    {st.gbp}
                  </p>
                </div>
                {channels.length > 0 && (
                  <label className="block text-[11px] font-bold text-ink/55 dark:text-fog/55">
                    {st.location}
                    <select
                      value={selectedId ?? ""}
                      onChange={(e) => {
                        setSelectedId(e.target.value || null);
                        setLastBulkFail(null);
                      }}
                      className="mt-1 block w-64 rounded-[2px] border border-ink/[0.10] bg-white px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
                    >
                      {channels.length > 1 && (
                        <option value={ALL}>{fill(st.allLocations, { n: fmt(channels.length) })}</option>
                      )}
                      {channels.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.display_name || st.locationFallback}
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
                eyebrow={st.lang.eyebrow}
            title={st.lang.title}
                subtitle={isBulk ? fill(st.lang.subAll, { n: fmt(bulkBranches.length) }) : fill(st.lang.subOne, { name: selectedName })}
              >
                <div>
                  <p className="mb-1.5 text-[12px] font-medium text-ink/60 dark:text-fog/60">
                    {st.lang.replyLabel}
                    {bulk?.varies.has("reply_language") ? <VariesBadge /> : null}
                  </p>
                  <div className="space-y-1.5">
                    {[
                      { id: "match", label: st.lang.matchLabel, hint: st.lang.matchHint },
                      { id: "en", label: st.lang.enLabel, hint: st.lang.enHint },
                      { id: "ar", label: st.lang.arLabel, hint: st.lang.arHint },
{ id: "ur", label: st.lang.urLabel, hint: st.lang.urHint },
{ id: "ur-Latn", label: st.lang.urLatnLabel, hint: st.lang.urLatnHint },
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
                <Field label={st.lang.dialectLabel} hint={st.lang.dialectHint} varies={bulk?.varies.has("dialect") ?? false}>
                  <select value={dialect} onChange={(e) => setDialect(e.target.value)} disabled={busy !== null || replyLang === "en" || replyLang === "ur" || replyLang === "ur-Latn"} className={selectCls}>
                    <option value="auto">{st.lang.dialectAuto}</option>
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
                      void saveCfg({ reply_language: replyLang, dialect }, st.lang.saved, "lang");
                      return;
                    }
                    const patch = { reply_language: replyLang, dialect };
                    requestBulkSave(
                      st.lang.confirmTitle,
                      [
                        fill(st.lang.lineLang, { v: replyLang === "en" ? st.lang.optEn : replyLang === "ar" ? st.lang.optAr : st.lang.optMatch }),
                        fill(st.lang.lineDialect, { v: dialectName(dialect) }),
                      ],
                      () => runBulkCfg(st.bulkNames.language, patch),
                      st.bulkNames.language,
                      (ids) => runBulkCfg(st.bulkNames.language, patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "lang" ? st.saving : bulk ? fill(st.applyN, { n: fmt(bulk.branches.length) }) : st.lang.save}
                </button>
              </Section>

              <Section eyebrow={st.tone.eyebrow} title={st.tone.title} subtitle={isBulk ? fill(st.tone.subAll, { n: fmt(bulkBranches.length) }) : fill(st.tone.subOne, { name: selectedName })}>
                <Field label={st.tone.label} varies={bulk?.varies.has("tone") ?? false}>
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
                      void saveCfg({ tone }, st.tone.saved, "tone");
                      return;
                    }
                    requestBulkSave(
                      st.tone.confirmTitle,
                      [fill(st.tone.line, { v: tone })],
                      () => runBulkCfg(st.bulkNames.tone, { tone }),
                      st.bulkNames.tone,
                      (ids) => runBulkCfg(st.bulkNames.tone, { tone }, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "tone" ? st.saving : bulk ? fill(st.applyN, { n: fmt(bulk.branches.length) }) : st.tone.save}
                </button>
              </Section>

              <Section
                eyebrow={st.marketing.eyebrow}
            title={st.marketing.title}
                subtitle={st.marketing.sub}
              >
                {(
                  [
                    ["promoProducts", "promoProducts", st.marketing.products, st.marketing.productsHint],
                    ["promoLinks", "promoLinks", st.marketing.links, st.marketing.linksHint],
                    ["promoRelevant", "promoRelevant", st.marketing.relevant, st.marketing.relevantHint],
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
                <Field label={st.marketing.maxLabel} varies={bulk?.varies.has("promoMax") ?? false}>
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
                      void saveCfg(patch, st.marketing.saved, "marketing");
                      return;
                    }
                    requestBulkSave(
                      st.marketing.confirmTitle,
                      [
                        fill(st.marketing.lineProducts, { v: promoProducts ? st.marketing.on : st.marketing.off }),
                        fill(st.marketing.lineLinks, { v: promoLinks ? st.marketing.on : st.marketing.off }),
                        fill(st.marketing.lineRelevant, { v: promoRelevant ? st.marketing.on : st.marketing.off }),
                        fill(st.marketing.lineMax, { v: fmt(promoMax) }),
                      ],
                      () => runBulkCfg(st.bulkNames.marketing, patch),
                      st.bulkNames.marketing,
                      (ids) => runBulkCfg(st.bulkNames.marketing, patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "marketing" ? st.saving : bulk ? fill(st.applyN, { n: fmt(bulk.branches.length) }) : st.marketing.save}
                </button>
              </Section>

              <Section
                eyebrow={st.edited.eyebrow}
            title={st.edited.title}
                subtitle={st.edited.sub}
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
                      {st.edited.label}
                      {bulk?.varies.has("editedAutopost") ? <VariesBadge /> : null}
                    </span>
                    <span className="block text-[11px] text-ink/45 dark:text-fog/45">
                      {st.edited.hint}
                    </span>
                  </span>
                </label>
                <button
                  onClick={() => {
                    const patch = { edited_review_autopost: editedAutopost };
                    if (!isBulk) {
                      void saveCfg(patch, st.edited.saved, "editedReview");
                      return;
                    }
                    requestBulkSave(
                      st.edited.confirmTitle,
                      [fill(st.edited.line, { v: editedAutopost ? st.edited.auto : st.edited.wait })],
                      () => runBulkCfg(st.bulkNames.edited, patch),
                      st.bulkNames.edited,
                      (ids) => runBulkCfg(st.bulkNames.edited, patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "editedReview" ? st.saving : bulk ? fill(st.applyN, { n: fmt(bulk.branches.length) }) : st.edited.save}
                </button>
              </Section>

              <Section
                eyebrow={st.handoff.eyebrow}
                title={st.handoff.title}
                subtitle={st.handoff.sub}
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
                      {st.handoff.label}
                      {bulk?.varies.has("handoffLink") ? <VariesBadge /> : null}
                    </span>
                    <span className="block text-[11px] text-ink/45 dark:text-fog/45">
                      {st.handoff.hint}
                    </span>
                  </span>
                </label>
                <button
                  onClick={() => {
                    const patch = { handoff_link_enabled: handoffLink };
                    if (!isBulk) {
                      void saveCfg(patch, st.handoff.saved, "handoffLink");
                      return;
                    }
                    requestBulkSave(
                      st.handoff.confirmTitle,
                      [fill(st.handoff.line, { v: handoffLink ? st.handoff.offered : st.handoff.hidden })],
                      () => runBulkCfg(st.bulkNames.waLink, patch),
                      "handoffLink",
                      (ids) => runBulkCfg(st.bulkNames.waLink, patch, ids),
                    );
                  }}
                  disabled={busy !== null}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                >
                  {busy === "handoffLink" ? st.saving : bulk ? fill(st.applyN, { n: fmt(bulk.branches.length) }) : st.handoff.save}
                </button>

                <div className="mt-4 border-t border-ink/[0.06] pt-4 dark:border-fog/[0.06]">
                  <label className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-ink dark:text-fog">
                    {st.handoff.ttlLabel}
                    {bulk?.varies.has("handoffTtl") ? <VariesBadge /> : null}
                    <select
                      value={handoffTtlDays}
                      onChange={(e) => setHandoffTtlDays(Number(e.target.value))}
                      disabled={busy !== null}
                      className={`${selectCls} w-32`}
                    >
                      {Array.from(new Set([1, 3, 7, 14, 30, handoffTtlDays]))
                        .sort((a, b) => a - b)
                        .map((days) => (
                          <option key={days} value={days}>
                            {days === 1 ? st.handoff.dayOne : fill(st.handoff.dayN, { n: fmt(days) })}
                          </option>
                        ))}
                    </select>
                  </label>
                  <p className="mt-1 text-[11px] leading-relaxed text-ink/45 dark:text-fog/45">
                    {st.handoff.ttlBody}
                  </p>
                  <button
                    onClick={() => {
                      const patch = { handoff_code_ttl_days: handoffTtlDays };
                      if (!isBulk) {
                        void saveCfg(patch, st.handoff.ttlSaved, "handoffTtl");
                        return;
                      }
                      requestBulkSave(
                        st.handoff.confirmTtlTitle,
                        [fill(st.handoff.confirmTtlLine, { n: fmt(handoffTtlDays) })],
                        () => runBulkCfg(st.handoff.ttlLabel, patch),
                        "handoffTtl",
                        (ids) => runBulkCfg(st.handoff.ttlLabel, patch, ids),
                      );
                    }}
                    disabled={busy !== null}
                    className="mt-2 rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
                  >
                    {busy === "handoffTtl" ? st.saving : bulk ? fill(st.applyN, { n: fmt(bulk.branches.length) }) : st.handoff.saveLifetime}
                  </button>
                </div>
              </Section>

              <p className="rounded-[2px] border border-ink/[0.06] bg-white/60 px-4 py-3 text-[12px] text-ink/55 dark:border-fog/[0.06] dark:bg-ink/60 dark:text-fog/55">
                {st.recap.repliesIn} <strong>{langName}</strong>
                {langName !== st.recap.langEn && <> ({dialectName(dialect)})</>} · {st.recap.tone} <strong className="capitalize">{tone}</strong> · {st.recap.country}{" "}
                <strong>{countryName}</strong> {st.recap.promo}{" "}
                <strong>{promoProducts || promoLinks ? promoMax === 1 ? st.recap.promoOnOne : fill(st.recap.promoOnN, { n: fmt(promoMax) }) : st.recap.promoOff}</strong>
                {" "}{st.recap.wa} <strong>{handoffLink ? st.recap.on : st.recap.off}</strong>
                {" "}{st.recap.ttl} <strong>{handoffTtlDays === 1 ? st.handoff.dayOne : fill(st.handoff.dayN, { n: fmt(handoffTtlDays) })}</strong>
              </p>
            </>
          ) : (
            <div className="rounded-[3px] border border-dashed border-ink/[0.12] bg-white/60 p-10 text-center dark:border-fog/[0.12] dark:bg-ink/60">
              <p className="text-[14px] font-semibold text-ink/70 dark:text-fog/70">
                {st.emptyGoogleTitle}
              </p>
              <p className="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-ink/45 dark:text-fog/45">
                {st.emptyGoogleBody}
              </p>
            </div>
          ))}
          </>
          )}

          {/* ── Social channels ───────────────────────────────────────── */}
          {tab === "social" && (
            <Section
              eyebrow={st.social.eyebrow}
              title={st.social.title}
              subtitle={st.social.sub}
            >
              {metaConnections.length === 0 ? (
                <p className="text-[12px] text-ink/45 dark:text-fog/45">
                  {st.social.empty}
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
                          {fill(st.social.connectedOn, { date: new Date(c.created_at).toLocaleDateString(dateLocale) })} · {c.status}
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
        eyebrow={st.danger.eyebrow}
        title={st.danger.title}
        subtitle={st.danger.sub}
      >
        <div className="space-y-2">
          {metaConnections.length === 0 ? (
            <p className="text-[12px] text-ink/40 dark:text-fog/40">{st.danger.empty}</p>
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
                    Connected {new Date(c.created_at).toLocaleDateString(dateLocale)}
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
                  {st.danger.disconnect}
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
        eyebrow={st.privacy.eyebrow}
        title={st.privacy.title}
        subtitle={st.privacy.sub}
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-ink/[0.06] bg-white px-4 py-3 dark:border-fog/[0.08] dark:bg-ink">
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-ink dark:text-fog">{st.privacy.exportTitle}</p>
              <p className="text-[11px] text-ink/40 dark:text-fog/40">
                {st.privacy.exportBody}
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
              {st.privacy.exportBtn}
            </button>
          </div>
          {deletion?.status === "pending" ? (
            <div className="rounded-[2px] border border-amber-500/30 bg-amber-500/[0.06] px-4 py-3">
              <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
                {st.privacy.delScheduled}
              </p>
              <p className="mt-1 text-[11px] text-ink/55 dark:text-fog/55">
                {st.privacy.delBodyPre}{" "}
                <strong>
                  {deletion.scheduled_for
                    ? new Date(deletion.scheduled_for).toLocaleDateString(dateLocale)
                    : st.privacy.delDateFallback}
                </strong>
                {st.privacy.delBodyPost}
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={async () => {
                    if (deletionBusy) return;
                    setDeletionBusy(true);
                    try {
                      const state = await cancelPersonalDataDeletion();
                      setDeletion(state);
                    } catch {
                      alert(st.privacy.cancelFailed);
                    } finally {
                      setDeletionBusy(false);
                    }
                  }}
                  disabled={deletionBusy}
                  className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-semibold text-ink transition hover:bg-ink/[0.04] disabled:opacity-50 dark:text-fog"
                >
                  {deletionBusy ? st.privacy.cancelling : st.privacy.keepAccount}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[2px] border border-red-500/20 bg-red-500/[0.04] px-4 py-3 dark:border-red-500/20 dark:bg-red-500/[0.06]">
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-red-600 dark:text-red-400">
                  {st.privacy.delTitle}
                </p>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">
                  {st.privacy.delBody}
                </p>
              </div>
              <button
                onClick={() => {
                  setDeletionConfirm("");
                  setDeletionModal(true);
                }}
                className="rounded-[2px] border border-red-500/40 px-3 py-1.5 text-[12px] font-semibold text-red-600 transition hover:bg-red-500/10 disabled:opacity-50 dark:text-red-400"
              >
                {st.privacy.delTitle}
              </button>
            </div>
          )}
        </div>
      </Section>



      {/* Type-to-confirm modal — one wrong glance should not delete a
          tenant's whole history, so the button stays dead until the exact
          phrase is typed. */}
      {deletionModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-md rounded-[3px] border border-red-500/30 bg-white p-5 shadow-xl dark:border-fog/[0.08] dark:bg-ink">
            <p className="text-[15px] font-bold text-red-600 dark:text-red-400">
              {st.privacy.modalTitle}
            </p>
            <p className="mt-2 text-[12px] leading-relaxed text-ink/70 dark:text-fog/70">
              {st.privacy.modalBodyPre}{" "}
              <strong>{st.privacy.modalDays}</strong>
              {st.privacy.modalBodyPost}
            </p>
            <details className="mt-3 rounded-[2px] border border-ink/[0.08] px-3 py-2 dark:border-fog/[0.1]">
              <summary className="cursor-pointer text-[11px] font-semibold text-ink/60 dark:text-fog/60">
                {st.privacy.modalDetails}
              </summary>
              <p className="mt-2 text-[11px] leading-relaxed text-ink/55 dark:text-fog/55">
                {st.privacy.modalDetailsBody}
              </p>
            </details>
            <label className="mt-3 block text-[11px] font-semibold text-ink/60 dark:text-fog/60">
              {st.privacy.typeConfirm}
              <input
                value={deletionConfirm}
                onChange={(e) => setDeletionConfirm(e.target.value)}
                placeholder="DELETE"
                className="mt-1 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2 text-[12px] tracking-widest text-ink outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/[0.12] dark:bg-ink dark:text-fog"
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeletionModal(false)}
                className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 dark:text-fog/70"
              >
                {st.privacy.keepAccount}
              </button>
              <button
                type="button"
                disabled={
                  deletionBusy ||
                  deletionConfirm.trim().toUpperCase() !== "DELETE"
                }
                onClick={async () => {
                  if (deletionBusy) return;
                  setDeletionBusy(true);
                  try {
                    const state = await requestPersonalDataDeletion();
                    setDeletion(state);
                    setDeletionModal(false);
                  } catch {
                    alert(st.privacy.scheduleFailed);
                  } finally {
                    setDeletionBusy(false);
                  }
                }}
                className="rounded-[2px] bg-red-600 px-3 py-1.5 text-[12px] font-bold text-white disabled:opacity-40"
              >
                {deletionBusy ? st.privacy.scheduling : st.privacy.delTitle}
              </button>
            </div>
          </div>
        </div>
      )}

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
              {fill(st.dangerModal.title, { provider: PROVIDER_LABELS[dangerTarget.provider] ?? dangerTarget.provider })}
            </p>
            <p className="mt-2 text-[12px] leading-relaxed text-ink/70 dark:text-fog/70">
              {st.dangerModal.bodyPre}{" "}
              <strong>{st.dangerModal.bodyPost}</strong>
            </p>
            <label className="mt-3 block text-[11px] font-semibold text-ink/55 dark:text-fog/55">
              {st.dangerModal.typePre} <span className="font-mono text-red-600 dark:text-red-400">DELETE MY DATA</span> {st.dangerModal.typePost}
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
                {st.dangerModal.cancel}
              </button>
              <button
                onClick={() => void deleteMetaConnection(dangerTarget)}
                disabled={dangerPhrase !== "DELETE MY DATA" || dangerBusy !== null}
                className="rounded-[2px] bg-red-600 px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-40"
              >
                {dangerBusy === dangerTarget.id ? st.dangerModal.deleting : st.dangerModal.deleteAll}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
