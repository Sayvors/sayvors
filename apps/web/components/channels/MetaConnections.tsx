"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  type MetaAsset,
  type MetaConnection,
  type MetaProvider,
  discoverInstagram,
  disconnectMeta,
  fetchMetaAssets,
  fetchMetaConnections,
  selectMetaAssets,
  validateMeta,
} from "@/lib/api-meta";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { useI18n } from "@/lib/i18n/I18nProvider";
import PlatformMark from "@/components/channels/PlatformMark";
import LogoLoader from "@/components/LogoLoader";

/*
 * Channel cards for the tenant's own Meta accounts.
 *
 * Data layer: TanStack Query. Connections and assets are cached under the
 * "meta" key namespace, so navigating away and back reuses the cache instead
 * of re-downloading. Every mutation invalidates the namespace and triggers a
 * background refetch — the same behaviour as the old refresh(), but without
 * the per-navigation storm.
 *
 * The card is a summary and a door: Connect sends the tenant to the guided
 * onboarding screen for that provider (/dashboard/channels/<provider>/connect)
 * where the Meta popup, pre-flight checks and asset pick live. Nothing here
 * opens a popup, so a card can never hang on a blocked window.
 */

const PROVIDERS: {
  key: MetaProvider;
  name: string;
  tint: string;
  enabled: boolean;
}[] = [
  { key: "whatsapp", name: "WhatsApp", tint: "bg-emerald-600/10", enabled: true },
  {
    key: "facebook",
    name: "Facebook",
    tint: "bg-blue-600/10",
    enabled: process.env.NEXT_PUBLIC_META_FACEBOOK_CONNECT_ENABLED === "true",
  },
  {
    key: "instagram",
    name: "Instagram",
    tint: "bg-pink-600/10",
    enabled: process.env.NEXT_PUBLIC_META_INSTAGRAM_CONNECT_ENABLED === "true",
  },
];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

const CONNECT_HREF: Record<MetaProvider, string> = {
  whatsapp: "/dashboard/channels/whatsapp/connect",
  facebook: "/dashboard/channels/facebook/connect",
  instagram: "/dashboard/channels/instagram/connect",
};

const HUB_HREF: Record<MetaProvider, string> = {
  whatsapp: "/dashboard/channels/whatsapp",
  facebook: "/dashboard/channels/facebook",
  instagram: "/dashboard/channels/instagram",
};

function assetLabel(a: MetaAsset): string {
  const base = a.name ?? a.username ?? a.phone ?? a.external_asset_id;
  return a.phone && base !== a.phone ? `${base} · ${a.phone}` : base;
}

export default function MetaConnections({
  onNotice,
}: {
  onNotice: (kind: "ok" | "err", text: string) => void;
}) {
  const { t } = useI18n();
  const m = t.dashboard.channels.meta;
  const providerDisplay = (provider: string): string =>
    PROVIDERS.find((x) => x.key === provider)?.name ?? provider;
  const providerBlurb = (provider: string): string => {
    if (provider === "whatsapp") return m.whatsappBlurb;
    if (provider === "facebook") return m.facebookBlurb;
    return m.instagramBlurb;
  };
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [picking, setPicking] = useState<MetaProvider | null>(null);
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const [confirmOff, setConfirmOff] = useState<MetaProvider | null>(null);

  const connectionsQuery = useQuery({
    queryKey: queryKeys.meta.connections(),
    queryFn: async () => {
      const data = await fetchMetaConnections();
      const map: Record<string, MetaConnection> = {};
      for (const c of data.connections ?? []) map[c.provider] = c;
      return map;
    },
    staleTime: 30 * 1000,
  });

  const assetsQuery = useQuery({
    queryKey: queryKeys.meta.assets("all"),
    queryFn: async () => {
      const amap: Record<string, MetaAsset[]> = {};
      await Promise.all(
        (["whatsapp", "facebook", "instagram"] as MetaProvider[]).map(async (p) => {
          try {
            const a = await fetchMetaAssets(p);
            amap[p] = a.assets ?? [];
          } catch {
            amap[p] = [];
          }
        })
      );
      return amap;
    },
    staleTime: 30 * 1000,
  });

  const connections = connectionsQuery.data ?? {};
  const assets = assetsQuery.data ?? {};

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["meta"] });
  }, [queryClient]);

  const openPicker = (provider: MetaProvider) => {
    const current = (assets[provider] ?? []).filter((a) => a.active).map((a) => a.id);
    setPicked((prev) => ({ ...prev, [provider]: current }));
    setPicking(provider);
  };

  const savePickMutation = useMutation({
    mutationFn: async (provider: MetaProvider) => {
      const providerPicked = picked[provider] ?? [];
      await selectMetaAssets(provider, providerPicked);
      return { provider, count: providerPicked.length };
    },
    onMutate: (provider) => { setBusy(`${provider}-save`); },
    onSuccess: ({ provider, count }) => {
      onNotice(
        "ok",
        count > 0
          ? fill(m.assetsOn, { provider: providerDisplay(provider), count })
          : fill(m.assetsOff, { provider: providerDisplay(provider) }),
      );
      setPicking(null);
      setPicked((prev) => ({ ...prev, [provider]: [] }));
      invalidate();
    },
    onError: (_err, provider) => {
      const count = (picked[provider] ?? []).length;
      onNotice(
        "err",
        count > 0 ? m.activateFailed : m.saveFailed,
      );
    },
    onSettled: () => { setBusy(null); },
  });

  const savePick = (provider: MetaProvider) => { savePickMutation.mutate(provider); };

  const recheckMutation = useMutation({
    mutationFn: async (provider: MetaProvider) => {
      const res = await validateMeta(provider);
      return { provider, status: res.status, detail: res.detail };
    },
    onMutate: (provider) => { setBusy(`${provider}-check`); },
    onSuccess: ({ provider, status, detail }) => {
      onNotice(status === "active" ? "ok" : "err", `${provider}: ${detail ?? status}`);
      invalidate();
    },
    onError: (e, provider) => {
      onNotice(
        "err",
        fill(m.validateFailed, {
          provider: providerDisplay(provider),
          message: e instanceof Error ? e.message : "request failed",
        }),
      );
    },
    onSettled: () => { setBusy(null); },
  });

  const recheck = (provider: MetaProvider) => { recheckMutation.mutate(provider); };

  const disconnectMutation = useMutation({
    mutationFn: async (provider: MetaProvider) => {
      await disconnectMeta(provider);
      return provider;
    },
    onMutate: (provider) => { setBusy(`${provider}-off`); },
    onSuccess: (provider) => {
      onNotice("ok", fill(m.disconnectedOk, { provider: providerDisplay(provider) }));
      setConfirmOff(null);
      invalidate();
    },
    onError: (_e, provider) => {
      onNotice("err", fill(m.disconnectFailed, { provider: providerDisplay(provider) }));
    },
    onSettled: () => { setBusy(null); },
  });

  const disconnect = (provider: MetaProvider) => { disconnectMutation.mutate(provider); };

  const discoverIgMutation = useMutation({
    mutationFn: async () => {
      const res = await discoverInstagram();
      return res.assets.length;
    },
    onMutate: () => { setBusy("instagram-discover"); },
    onSuccess: (count) => {
      onNotice("ok", fill(m.foundIg, { count }));
      invalidate();
      const current = (assets.instagram ?? []).filter((a) => a.active).map((a) => a.id);
      setPicked((prev) => ({ ...prev, instagram: current }));
      setPicking("instagram");
    },
    onError: (e) => {
      onNotice("err", e instanceof Error ? e.message : m.connectFbFirst);
    },
    onSettled: () => { setBusy(null); },
  });

  const discoverIg = () => { discoverIgMutation.mutate(); };

  const pickerAssets = picking
    ? picking === "whatsapp"
      ? (assets.whatsapp ?? []).filter((a) => a.asset_type === "phone_number")
      : assets[picking] ?? []
    : [];

  return (
    <>
      {PROVIDERS.filter((p) => p.enabled).map((p) => {
        const conn = connections[p.key];
        const list = assets[p.key] ?? [];
        const visible = p.key === "whatsapp" ? list.filter((a) => a.asset_type === "phone_number") : list;
        const active = visible.filter((a) => a.active);
        const isDisconnected = !conn || conn.status === "revoked";
        const needsAsset = !isDisconnected && active.length === 0;
        const label = isDisconnected
          ? providerBlurb(p.key)
          : active.length > 0
            ? active
                .map(
                  (a) =>
                    (p.key === "whatsapp" ? a.phone ?? a.name : a.name ?? a.username ?? a.phone) ??
                    a.external_asset_id
                )
                .join(", ")
            : `Connected · ${p.key === "whatsapp" ? m.noNumber : m.noAsset}`;

        return (
          <article
            key={p.key}
            className="flex flex-col rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
          >
            <div className="flex items-start gap-3">
              <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${p.tint}`}>
                <PlatformMark platform={p.key} size={22} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <p className="text-[13.5px] font-semibold text-ink dark:text-fog">{p.name}</p>
                  <StatusPill conn={conn} />
                </div>
                <p className="mt-0.5 truncate text-[11.5px] text-ink/45 dark:text-fog/45" title={label}>
                  {label}
                </p>
                {!p.enabled && (
                  <p className="mt-0.5 text-[10.5px] font-semibold text-amber-600 dark:text-amber-400">
                    {m.paused}
                  </p>
                )}
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-ink/[0.05] pt-3 dark:border-fog/[0.06]">
              {isDisconnected ? (
                p.enabled ? (
                  <Link
                    href={CONNECT_HREF[p.key]}
                    className="inline-flex min-h-8 items-center rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white shadow-sm outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2"
                  >
                    {m.connect}
                  </Link>
                ) : (
                  <span className="inline-flex min-h-8 items-center rounded-lg bg-ink/[0.05] px-3 text-[12px] font-semibold text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45">
                    {m.comingSoon}
                  </span>
                )
              ) : (
                <>
                  {needsAsset && p.key === "facebook" && (
                    <button
                      onClick={() => openPicker("facebook")}
                      className="inline-flex min-h-8 items-center rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
                    >
                      {m.pickPages}
                    </button>
                  )}
                  {needsAsset && p.key === "instagram" && (
                    <button
                      onClick={() => void discoverIg()}
                      disabled={busy === "instagram-discover"}
                      className="inline-flex min-h-8 items-center rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
                    >
                      {busy === "instagram-discover" ? m.discovering : m.discover}
                    </button>
                  )}
                  <button
                    onClick={() => openPicker(p.key)}
                    className="min-h-8 rounded-lg px-2.5 text-[11.5px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.04] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-fog/60 dark:hover:bg-fog/[0.05]"
                  >
                    {m.manage}
                  </button>
                  <button
                    onClick={() => void recheck(p.key)}
                    disabled={busy === `${p.key}-check`}
                    className="min-h-8 rounded-lg px-2.5 text-[11.5px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.04] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50 dark:text-fog/60 dark:hover:bg-fog/[0.05]"
                  >
                    {busy === `${p.key}-check` ? m.checking : m.recheck}
                  </button>
                  <button
                    onClick={() => setConfirmOff(p.key)}
                    disabled={busy === `${p.key}-off`}
                    className="min-h-8 rounded-lg px-2.5 text-[11.5px] font-semibold text-red-600 outline-none transition hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-red-500/40 disabled:opacity-50 dark:text-red-400"
                  >
                    {m.disconnect}
                  </button>
                  <Link
                    href={HUB_HREF[p.key]}
                    className="ml-auto hidden min-h-8 items-center rounded-lg px-2.5 text-[11.5px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06] sm:inline-flex"
                  >
                    {m.open}
                  </Link>
                </>
              )}
            </div>
          </article>
        );
      })}

      {/* ── Asset picker modal ─────────────────────────────────── */}
      {picking && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Choose ${picking} assets`}
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/45 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setPicking(null);
          }}
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-4 shadow-xl dark:border-fog/[0.08] dark:bg-ink sm:p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[15px] font-bold text-ink dark:text-fog">
                  {picking === "whatsapp"
                    ? m.chooseNumbers
                    : fill(m.chooseAssets, { provider: picking })}
                </h2>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink/45 dark:text-fog/45">
                  {picking === "whatsapp" ? m.pickNumbers : m.pickAssets}
                </p>
              </div>
              <button
                onClick={() => setPicking(null)}
                aria-label={m.close}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink/40 outline-none transition hover:bg-ink/[0.05] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-fog/40 dark:hover:bg-fog/[0.06]"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4" aria-hidden>
                  <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            <div className="mt-3 max-h-[50vh] space-y-2 overflow-y-auto">
              {picking === "instagram" && (
                <button
                  onClick={() => void discoverIg()}
                  disabled={busy === "instagram-discover"}
                  className="w-full rounded-lg border border-deep-violet/25 px-3 py-2 text-[11.5px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06] disabled:opacity-50"
                >
                  {busy === "instagram-discover" ? m.discovering : m.discoverPages}
                </button>
              )}
              {pickerAssets.length === 0 && (
                <p className="rounded-lg bg-ink/[0.03] px-3 py-2.5 text-[12px] text-ink/45 dark:bg-fog/[0.04] dark:text-fog/45">
                  {m.noAssets}
                </p>
              )}
              {pickerAssets.map((a) => {
                const checked = (picked[picking] ?? []).includes(a.id);
                return (
                  <label
                    key={a.id}
                    className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-ink/[0.06] px-3 py-2 transition hover:border-deep-violet/25 dark:border-fog/[0.08]"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setPicked((prev) => {
                          const current = prev[picking] ?? [];
                          return {
                            ...prev,
                            [picking]: current.includes(a.id)
                              ? current.filter((x) => x !== a.id)
                              : [...current, a.id],
                          };
                        })
                      }
                      className="h-4 w-4 shrink-0 accent-[#5b2d8e]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-semibold text-ink dark:text-fog">
                        {assetLabel(a)}
                      </span>
                      <span className="block truncate text-[10.5px] text-ink/45 dark:text-fog/45">
                        {a.asset_type}
                        {a.status !== "connected" ? ` · ${a.status}` : ""}
                        {a.active ? ` · ${m.activeTag}` : ""}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>

            <div className="mt-4 flex flex-col-reverse gap-2 border-t border-ink/[0.05] pt-3 dark:border-fog/[0.06] sm:flex-row sm:justify-end">
              <button
                onClick={() => setPicking(null)}
                className="min-h-9 rounded-lg px-3 text-[12px] font-semibold text-ink/55 transition hover:bg-ink/[0.04] dark:text-fog/55 dark:hover:bg-fog/[0.05]"
              >
                {t.common.cancel}
              </button>
              <button
                onClick={() => void savePick(picking)}
                disabled={busy === `${picking}-save`}
                className="inline-flex min-h-9 items-center justify-center rounded-lg bg-deep-violet px-3.5 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
              >
                {busy === `${picking}-save` ? (
                  <LogoLoader size={14} />
                ) : (picked[picking] ?? []).length === 0 ? (
                  m.deselectAll
                ) : (
                  fill(m.useSelected, { count: (picked[picking] ?? []).length })
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Disconnect confirmation — soft disconnect, history kept ── */}
      {confirmOff && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/45 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setConfirmOff(null);
          }}
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-4 shadow-xl dark:border-fog/[0.08] dark:bg-ink sm:p-5">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">
              {fill(m.confirmTitle, { provider: providerDisplay(confirmOff) })}
            </h2>
            <p className="mt-2 text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">
              {m.confirmDesc}
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-ink/40 dark:text-fog/40">
              {m.wipe}{" "}
              <Link href="/dashboard/settings" className="font-semibold text-red-600 underline underline-offset-2 dark:text-red-400">
                Settings → Danger zone
              </Link>
              .
            </p>
            <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                onClick={() => setConfirmOff(null)}
                disabled={busy === `${confirmOff}-off`}
                className="min-h-9 rounded-lg px-3 text-[12px] font-semibold text-ink/55 transition hover:bg-ink/[0.04] dark:text-fog/55 dark:hover:bg-fog/[0.05]"
              >
                {t.common.cancel}
              </button>
              <button
                onClick={() => void disconnect(confirmOff)}
                disabled={busy === `${confirmOff}-off`}
                className="min-h-9 rounded-lg bg-red-600 px-3.5 text-[12px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {busy === `${confirmOff}-off` ? m.disconnecting : m.disconnect}
              </button>
            </div>
          </div>
        </div>
      )}

    </>
  );
}

function StatusPill({ conn }: { conn: MetaConnection | undefined }) {
  const { t } = useI18n();
  const m = t.dashboard.channels.meta;
  if (!conn || conn.status === "revoked") {
    return (
      <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45">
        {m.notConnected}
      </span>
    );
  }
  const active = conn.status === "active";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
        active
          ? "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300"
          : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
      }`}
    >
      {active ? m.connected : conn.status.replace("_", " ")}
    </span>
  );
}
