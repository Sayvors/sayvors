"use client";

import { useCallback, useEffect, useState } from "react";
import {
  MetaAsset,
  MetaConnection,
  MetaProvider,
  discoverInstagram,
  disconnectMeta,
  fetchMetaAssets,
  fetchMetaConnections,
  postWhatsAppSession,
  selectMetaAssets,
  startMetaConnect,
  validateMeta,
} from "@/lib/api-meta";

declare global {
  interface Window {
    FB?: {
      init: (opts: { appId: string; version: string; xfbml?: boolean }) => void;
      login: (
        cb: (resp: {
          authResponse?: { code?: string; accessToken?: string } | null;
          status?: string;
        }) => void,
        opts: Record<string, unknown>
      ) => void;
      Event?: {
        subscribe: (event: string, cb: (resp: Record<string, unknown>) => void) => void;
        unsubscribe: (event: string, cb: (resp: Record<string, unknown>) => void) => void;
      };
    };
    fbAsyncInit?: () => void;
  }
}

const PROVIDERS: { key: MetaProvider; name: string; blurb: string; icon: string; color: string }[] = [
  { key: "whatsapp", name: "WhatsApp", blurb: "Auto-reply to customer chats", icon: "💬", color: "from-emerald-500 to-green-600" },
  { key: "facebook", name: "Facebook", blurb: "Manage your Page + comments", icon: "📘", color: "from-blue-500 to-blue-600" },
  { key: "instagram", name: "Instagram", blurb: "Comments + DMs via your Page", icon: "📸", color: "from-pink-500 to-purple-500" },
];

function loadFacebookSdk(): Promise<void> {
  if (typeof document === "undefined") return Promise.resolve();
  if (document.getElementById("facebook-jssdk")) {
    if (window.FB && typeof window.FB.init === "function") return Promise.resolve();
    // SDK loaded but not ready yet — poll briefly (SDK init is async).
    return new Promise((resolve) => {
      const interval = setInterval(() => {
        if (window.FB && typeof window.FB.init === "function") {
          clearInterval(interval);
          resolve();
        }
      }, 100);
      setTimeout(() => { clearInterval(interval); resolve(); }, 3000);
    });
  }
  return new Promise((resolve) => {
    window.fbAsyncInit = () => resolve();
    const s = document.createElement("script");
    s.id = "facebook-jssdk";
    s.src = "https://connect.facebook.net/en_US/sdk.js";
    s.async = true;
    s.defer = true;
    s.onload = () => {
      if (window.FB && typeof window.FB.init === "function") resolve();
      else {
        // SDK may initialize after load event — poll briefly then resolve.
        const interval = setInterval(() => {
          if (window.FB && typeof window.FB.init === "function") {
            clearInterval(interval);
            resolve();
          }
        }, 100);
        setTimeout(() => { clearInterval(interval); resolve(); }, 3000);
      }
    };
    s.onerror = () => resolve();
    document.head.appendChild(s);
  });
}

export default function MetaConnections({
  onNotice,
}: {
  onNotice: (kind: "ok" | "err", text: string) => void;
}) {
  const [connections, setConnections] = useState<Record<string, MetaConnection>>({});
  const [assets, setAssets] = useState<Record<string, MetaAsset[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [picking, setPicking] = useState<MetaProvider | null>(null);
  const [picked, setPicked] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchMetaConnections();
      const map: Record<string, MetaConnection> = {};
      for (const c of data.connections ?? []) map[c.provider] = c;
      setConnections(map);
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
      setAssets(amap);
    } catch {
      /* backend down — cards still render */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const connectOAuth = async (provider: MetaProvider) => {
    setBusy(provider);
    try {
      const entry = await startMetaConnect(provider);
      if (!entry.auth_url) {
        onNotice("err", `${provider} connect is not configured yet.`);
        return;
      }
      window.location.href = entry.auth_url;
    } catch {
      onNotice("err", `Could not start ${provider} connect.`);
      setBusy(null);
    }
  };

  const connectWhatsApp = async () => {
    setBusy("whatsapp");
    try {
      const entry = await startMetaConnect("whatsapp");
      if (!entry.fb_app_id || !entry.fb_config_id) {
        onNotice("err", "WhatsApp onboarding is not configured yet (META_WHATSAPP_CONFIG_ID).");
        setBusy(null);
        return;
      }
      await loadFacebookSdk();
      if (!window.FB) {
        onNotice("err", "Could not load the Meta SDK. Check your connection and retry.");
        setBusy(null);
        return;
      }
      window.FB.init({ appId: entry.fb_app_id, version: entry.graph_api_version ?? "v26.0", xfbml: false });

      // Capture the Embedded Signup session payload (waba/phone/business ids).
      const session: Record<string, unknown> = {};
      const onSignupEvent = (resp: Record<string, unknown>) => {
        const data = (resp.data ?? resp) as Record<string, unknown>;
        for (const k of ["waba_id", "phone_number_id", "business_id"]) {
          if (typeof data[k] === "string") session[k] = data[k];
        }
      };
      try {
        window.FB.Event?.subscribe("WA_EMBEDDED_SIGNUP", onSignupEvent);
      } catch {
        /* older SDK — continue without session capture */
      }

      window.FB.login(
        async (loginResp) => {
          try {
            window.FB?.Event?.unsubscribe("WA_EMBEDDED_SIGNUP", onSignupEvent);
          } catch {
            /* ignore */
          }
          const code = loginResp?.authResponse?.code ?? null;
          if (!code && Object.keys(session).length === 0) {
            onNotice("err", "WhatsApp onboarding was cancelled.");
            setBusy(null);
            return;
          }
          try {
            const res = await postWhatsAppSession({
              state: entry.state,
              code,
              waba_id: (session.waba_id as string) ?? null,
              phone_number_id: (session.phone_number_id as string) ?? null,
              business_id: (session.business_id as string) ?? null,
            });
            onNotice("ok", `WhatsApp connected! ${res.assets_found} asset(s) found — pick which number to use.`);
            setPicked([]);
            setPicking("whatsapp");
            await refresh();
          } catch {
            onNotice("err", "WhatsApp session failed. Please try again.");
          } finally {
            setBusy(null);
          }
        },
        {
          config_id: entry.fb_config_id,
          response_type: "code",
          override_default_response_type: true,
          extras: { setup: {}, sessionInfoVersion: "3" },
        }
      );
    } catch {
      onNotice("err", "Could not start WhatsApp connect.");
      setBusy(null);
    }
  };

  const savePick = async (provider: MetaProvider) => {
    if (picked.length === 0) return;
    setBusy(`${provider}-save`);
    try {
      await selectMetaAssets(provider, picked);
      onNotice("ok", `${provider} asset(s) activated.`);
      setPicking(null);
      setPicked([]);
      await refresh();
    } catch {
      onNotice("err", "Could not activate the selected assets.");
    } finally {
      setBusy(null);
    }
  };

  const recheck = async (provider: MetaProvider) => {
    setBusy(`${provider}-check`);
    try {
      const res = await validateMeta(provider);
      onNotice(res.status === "active" ? "ok" : "err", `${provider}: ${res.detail ?? res.status}`);
      await refresh();
    } catch {
      onNotice("err", `Could not validate ${provider}.`);
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async (provider: MetaProvider) => {
    setBusy(`${provider}-off`);
    try {
      await disconnectMeta(provider);
      onNotice("ok", `${provider} disconnected.`);
      await refresh();
    } catch {
      onNotice("err", `Could not disconnect ${provider}.`);
    } finally {
      setBusy(null);
    }
  };

  const discoverIg = async () => {
    setBusy("instagram-discover");
    try {
      const res = await discoverInstagram();
      onNotice("ok", `Found ${res.assets.length} Instagram account(s) — pick which to use.`);
      setPicked([]);
      setPicking("instagram");
      await refresh();
    } catch (e) {
      onNotice("err", e instanceof Error ? e.message : "Connect Facebook first, then discover Instagram.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
        Meta — your own business accounts
      </p>
      {PROVIDERS.map((p) => {
        const conn = connections[p.key];
        const list = assets[p.key] ?? [];
        const active = list.filter((a) => a.active);
        const label =
          active.length > 0
            ? active.map((a) => a.name ?? a.username ?? a.phone ?? a.external_asset_id).join(", ")
            : conn
              ? `Connected (${conn.status})`
              : p.blurb;
        return (
          <div key={p.key}>
            <div className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
              <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${p.color} text-[22px] text-white shadow-sm`}>
                {p.icon}
              </div>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-[14px] font-semibold text-ink dark:text-fog">
                  {p.name}
                  {conn && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                        conn.status === "active"
                          ? "bg-emerald-600/15 text-emerald-700 dark:text-emerald-300"
                          : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                      }`}
                    >
                      {conn.status === "active" ? "Connected" : conn.status.replace("_", " ")}
                    </span>
                  )}
                </p>
                <p className="truncate text-[12px] text-ink/40 dark:text-fog/40">{label}</p>
              </div>
              {!conn ? (
                <button
                  onClick={() => (p.key === "whatsapp" ? connectWhatsApp() : connectOAuth(p.key))}
                  disabled={busy === p.key}
                  className="rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  {busy === p.key ? "…" : "Connect"}
                </button>
              ) : (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => {
                      setPicked(list.filter((a) => a.active).map((a) => a.id));
                      setPicking(picking === p.key ? null : p.key);
                    }}
                    className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:text-fog/60"
                  >
                    Manage
                  </button>
                  <button
                    onClick={() => recheck(p.key)}
                    disabled={busy === `${p.key}-check`}
                    className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:text-fog/60 disabled:opacity-50"
                  >
                    Re-check
                  </button>
                  <button
                    onClick={() => disconnect(p.key)}
                    disabled={busy === `${p.key}-off`}
                    className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-red-600 transition hover:bg-red-500/10 disabled:opacity-50"
                  >
                    Disconnect
                  </button>
                </div>
              )}
            </div>

            {/* Asset picker */}
            {picking === p.key && (
              <div className="mt-2 space-y-2 rounded-xl border border-ink/[0.06] bg-white/70 p-3 dark:border-fog/[0.06] dark:bg-ink/60">
                {p.key === "instagram" && (
                  <button
                    onClick={discoverIg}
                    disabled={busy === "instagram-discover"}
                    className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                  >
                    {busy === "instagram-discover" ? "Discovering…" : "Discover from my Pages"}
                  </button>
                )}
                {list.length === 0 && <p className="text-[12px] text-ink/40">No assets found yet — connect again or retry.</p>}
                {list.map((a) => (
                  <label key={a.id} className="flex cursor-pointer items-center gap-2.5 text-[12px]">
                    <input
                      type="checkbox"
                      checked={picked.includes(a.id)}
                      onChange={() =>
                        setPicked((prev) => (prev.includes(a.id) ? prev.filter((x) => x !== a.id) : [...prev, a.id]))
                      }
                      className="h-4 w-4 accent-[#5b2d8e]"
                    />
                    <span className="font-semibold">{a.name ?? a.username ?? a.phone ?? a.external_asset_id}</span>
                    <span className="text-ink/40">
                      {a.asset_type}
                      {a.status !== "connected" ? ` · ${a.status}` : ""}
                      {a.active ? " · active" : ""}
                    </span>
                  </label>
                ))}
                <div className="flex gap-2">
                  <button
                    onClick={() => savePick(p.key)}
                    disabled={picked.length === 0 || busy === `${p.key}-save`}
                    className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                  >
                    {busy === `${p.key}-save` ? "Saving…" : `Use selected (${picked.length})`}
                  </button>
                  <button
                    onClick={() => setPicking(null)}
                    className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-ink/40"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
