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
  blurb: string;
  tint: string;
}[] = [
  { key: "whatsapp", name: "WhatsApp", blurb: "AI replies to customer chats", tint: "bg-emerald-600/10" },
  { key: "facebook", name: "Facebook", blurb: "Page comments and Messenger", tint: "bg-blue-600/10" },
  { key: "instagram", name: "Instagram", blurb: "Comments and DMs via your Page", tint: "bg-pink-600/10" },
];

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
      onNotice("ok", count > 0 ? `${provider} asset(s) activated.` : `${provider} assets deselected — their data is hidden until you pick them again.`);
      setPicking(null);
      setPicked((prev) => ({ ...prev, [provider]: [] }));
      invalidate();
    },
    onError: (_err, provider) => {
      const count = (picked[provider] ?? []).length;
      onNotice("err", count > 0 ? "Could not activate the selected assets." : "Could not save the selection.");
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
      onNotice("err", `Could not validate ${provider}: ${e instanceof Error ? e.message : "request failed"}`);
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
      onNotice("ok", `${provider} disconnected. Your messages are kept.`);
      setConfirmOff(null);
      invalidate();
    },
    onError: (_e, provider) => {
      onNotice("err", `Could not disconnect ${provider}.`);
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
      onNotice("ok", `Found ${count} Instagram account(s) — pick which to use.`);
      invalidate();
      const current = (assets.instagram ?? []).filter((a) => a.active).map((a) => a.id);
      setPicked((prev) => ({ ...prev, instagram: current }));
      setPicking("instagram");
    },
    onError: (e) => {
      onNotice("err", e instanceof Error ? e.message : "Connect Facebook first, then discover Instagram.");
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
      {PROVIDERS.map((p) => {
        const conn = connections[p.key];
        const list = assets[p.key] ?? [];
        const visible = p.key === "whatsapp" ? list.filter((a) => a.asset_type === "phone_number") : list;
        const active = visible.filter((a) => a.active);
        const isDisconnected = !conn || conn.status === "revoked";
        const needsAsset = !isDisconnected && active.length === 0;
        const label = isDisconnected
          ? p.blurb
          : active.length > 0
            ? active
                .map(
                  (a) =>
                    (p.key === "whatsapp" ? a.phone ?? a.name : a.name ?? a.username ?? a.phone) ??
                    a.external_asset_id
                )
                .join(", ")
            : `Connected · no ${p.key === "whatsapp" ? "number" : "asset"} selected`;

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
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-ink/[0.05] pt-3 dark:border-fog/[0.06]">
              {isDisconnected ? (
                <Link
                  href={CONNECT_HREF[p.key]}
                  className="inline-flex min-h-8 items-center rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white shadow-sm outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2"
                >
                  Connect
                </Link>
              ) : (
                <>
                  {needsAsset && p.key === "facebook" && (
                    <button
                      onClick={() => openPicker("facebook")}
                      className="inline-flex min-h-8 items-center rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
                    >
                      Pick your Pages
                    </button>
                  )}
                  {needsAsset && p.key === "instagram" && (
                    <button
                      onClick={() => void discoverIg()}
                      disabled={busy === "instagram-discover"}
                      className="inline-flex min-h-8 items-center rounded-lg bg-deep-violet px-3 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
                    >
                      {busy === "instagram-discover" ? "Discovering…" : "Discover accounts"}
                    </button>
                  )}
                  <button
                    onClick={() => openPicker(p.key)}
                    className="min-h-8 rounded-lg px-2.5 text-[11.5px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.04] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-fog/60 dark:hover:bg-fog/[0.05]"
                  >
                    Manage
                  </button>
                  <button
                    onClick={() => void recheck(p.key)}
                    disabled={busy === `${p.key}-check`}
                    className="min-h-8 rounded-lg px-2.5 text-[11.5px] font-semibold text-ink/60 outline-none transition hover:bg-ink/[0.04] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50 dark:text-fog/60 dark:hover:bg-fog/[0.05]"
                  >
                    {busy === `${p.key}-check` ? "Checking…" : "Re-check"}
                  </button>
                  <button
                    onClick={() => setConfirmOff(p.key)}
                    disabled={busy === `${p.key}-off`}
                    className="min-h-8 rounded-lg px-2.5 text-[11.5px] font-semibold text-red-600 outline-none transition hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-red-500/40 disabled:opacity-50 dark:text-red-400"
                  >
                    Disconnect
                  </button>
                  <Link
                    href={HUB_HREF[p.key]}
                    className="ml-auto hidden min-h-8 items-center rounded-lg px-2.5 text-[11.5px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06] sm:inline-flex"
                  >
                    Open →
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
                    ? "Which numbers should Sayvors use?"
                    : `Which ${picking} assets should Sayvors use?`}
                </h2>
                <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink/45 dark:text-fog/45">
                  {picking === "whatsapp"
                    ? "Pick every number the AI may answer on — you can change this later."
                    : "Only the checked assets are visible in Sayvors."}
                </p>
              </div>
              <button
                onClick={() => setPicking(null)}
                aria-label="Close"
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
                  {busy === "instagram-discover" ? "Discovering…" : "Discover from my Pages"}
                </button>
              )}
              {pickerAssets.length === 0 && (
                <p className="rounded-lg bg-ink/[0.03] px-3 py-2.5 text-[12px] text-ink/45 dark:bg-fog/[0.04] dark:text-fog/45">
                  No assets found yet — connect again or retry.
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
                        {a.active ? " · active" : ""}
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
                Cancel
              </button>
              <button
                onClick={() => void savePick(picking)}
                disabled={busy === `${picking}-save`}
                className="inline-flex min-h-9 items-center justify-center rounded-lg bg-deep-violet px-3.5 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
              >
                {busy === `${picking}-save` ? (
                  <LogoLoader size={14} />
                ) : (picked[picking] ?? []).length === 0 ? (
                  "Deselect all"
                ) : (
                  `Use selected (${(picked[picking] ?? []).length})`
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
              Disconnect {PROVIDERS.find((x) => x.key === confirmOff)?.name}?
            </h2>
            <p className="mt-2 text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">
              Your conversations and history are kept — everything is back the moment you reconnect.
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-ink/40 dark:text-fog/40">
              Want to wipe your data instead? Permanently disconnect and delete everything from{" "}
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
                Cancel
              </button>
              <button
                onClick={() => void disconnect(confirmOff)}
                disabled={busy === `${confirmOff}-off`}
                className="min-h-9 rounded-lg bg-red-600 px-3.5 text-[12px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {busy === `${confirmOff}-off` ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          </div>
        </div>
      )}

    </>
  );
}

function StatusPill({ conn }: { conn: MetaConnection | undefined }) {
  if (!conn || conn.status === "revoked") {
    return (
      <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45">
        Not connected
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
      {active ? "Connected" : conn.status.replace("_", " ")}
    </span>
  );
}
