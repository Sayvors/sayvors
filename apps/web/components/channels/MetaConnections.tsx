"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  MetaAsset,
  MetaConnection,
  MetaProvider,
  discoverInstagram,
  disconnectMeta,
  fetchMetaAssets,
  fetchMetaConnections,
  postWhatsAppSession,
  registerWhatsAppNumber,
  selectMetaAssets,
  startMetaConnect,
  validateMeta,
} from "@/lib/api-meta";
import { getProfile, updateResponseStyle, updateVoiceReplies } from "@/lib/api-profile";

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

const RESPONSE_STYLE_OPTIONS = [
  {
    value: "concise",
    label: "Concise",
    desc: "Send clear, compact responses as a single message.",
  },
  {
    value: "human",
    label: "Human-like",
    desc: "Use natural short WhatsApp messages when appropriate.",
  },
] as const;

const VOICE_REPLY_OPTIONS = [
  {
    value: "off",
    label: "Off",
    desc: "Never send voice notes — text only.",
  },
  {
    value: "simple",
    label: "Simple",
    desc: "Short voice notes with clear built-in voices.",
  },
  {
    value: "advanced",
    label: "Advanced",
    desc: "Short voice notes with premium AI voices.",
  },
] as const;

// Same-origin proxy (backend /api/v1/meta/connect-sdk): ad-blockers match
// the facebook.net domain and common SDK filenames — this route has
// neither. Falls back to nothing — if our own API is unreachable the app
// is broken anyway.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FB_SDK_SRC = `${API_BASE}/api/v1/meta/connect-sdk`;

// sdk.js is a 12KB bootstrap that defines a STUB window.FB immediately
// (init/login/Event all exist but only buffer calls) and loads the real
// 272KB bundle from connect.facebook.net afterwards. So "FB.init exists"
// is NOT a readiness signal — the stub satisfies it. The real bundle
// fires window.fbAsyncInit when ready; key readiness on that. Calling
// FB.login against the stub buffers the call and replays it outside the
// click gesture (or never, if facebook.net is blocked) — which is how
// the Meta popup gets silently blocked. Hence: wait for fbAsyncInit.
let sdkPromise: Promise<void> | null = null;
let sdkReady = false;

function loadFacebookSdk(): Promise<void> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return Promise.resolve();
  }
  if (sdkReady && window.FB && typeof window.FB.init === "function") {
    return Promise.resolve();
  }
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise<void>((resolve, reject) => {
    let settled = false;
    const done = () => {
      sdkReady = true; // mark even after a timeout-fail: a late bundle is still ready
      if (!settled) {
        settled = true;
        resolve();
      }
    };
    const fail = (code: string) => {
      if (!settled) {
        settled = true;
        sdkPromise = null; // allow a retry on the next click
        reject(new Error(code));
      }
    };
    const deadline = setTimeout(() => fail("SDK_TIMED_OUT"), 12000);
    // Set before injecting the tag: the real bundle calls this when ready.
    window.fbAsyncInit = () => {
      clearTimeout(deadline);
      done();
    };
    // A previous attempt already injected the tag — fbAsyncInit above
    // resolves either way (bundle may still arrive).
    if (document.getElementById("facebook-jssdk")) return;
    const s = document.createElement("script");
    s.id = "facebook-jssdk";
    s.src = FB_SDK_SRC;
    s.async = true;
    // onerror = the browser refused the script (ad-blocker, shields,
    // tracking prevention, firewall) — retrying the same tag won't help.
    s.onerror = () => {
      clearTimeout(deadline);
      fail("SDK_BLOCKED");
    };
    document.head.appendChild(s);
  });
  return sdkPromise;
}

/** Name plus number — a name alone ("BM") reads as a duplicate of the WABA
 *  that shares it. */
function assetLabel(a: MetaAsset): string {
  const base = a.name ?? a.username ?? a.phone ?? a.external_asset_id;
  return a.phone && base !== a.phone ? `${base} · ${a.phone}` : base;
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
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  // Gate the WhatsApp button on SDK readiness: FB.login must run inside
  // the click gesture or the popup is silently blocked ("…" hang / flash).
  const [sdkLoading, setSdkLoading] = useState(true);
  // 6-digit two-step PIN, collected ONLY when Meta reports the connected number
  // could not be registered. Asking for it before Embedded Signup is
  // meaningless: the number does not exist in our DB until the popup returns,
  // and many tenants do not know their PIN until they go and set it.
  const [pinDraft, setPinDraft] = useState("");
  // phone_number_id awaiting registration (null = nothing pending).
  const [pendingReg, setPendingReg] = useState<string | null>(null);
  // WhatsApp onboarding mode selection
  const [waMode, setWaMode] = useState<"standard" | "coexistence" | null>(null);
  // Disconnect confirmation. `wipeData` upgrades the disconnect to a full
  // purge (messages, channels, assets, connection) so reconnecting starts
  // from scratch; unchecked, it is the old soft disconnect that keeps history.
  const [confirmOff, setConfirmOff] = useState<MetaProvider | null>(null);
  const [wipeData, setWipeData] = useState(false);
  // Tenant-level WhatsApp response style — a real account setting (the same
  // one the WhatsApp consumer reads per incoming message).
  const [responseStyle, setResponseStyle] = useState<string>("concise");
  const [styleStatus, setStyleStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  // Tenant-level WhatsApp voice replies tier (the engine behind each tier is
  // admin-managed; the tenant only ever picks off / simple / advanced).
  const [voiceReplies, setVoiceReplies] = useState<string>("off");
  const [voiceStatus, setVoiceStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const params = useSearchParams();
  const urlProvider = (params?.get("provider") as MetaProvider | null) ?? null;
  const activeFilter = urlProvider;

  useEffect(() => {
    let cancelled = false;
    getProfile()
      .then((p) => {
        if (!cancelled) {
          setResponseStyle(p.response_style === "human" ? "human" : "concise");
          setVoiceReplies(
            p.voice_replies === "simple" || p.voice_replies === "advanced"
              ? p.voice_replies
              : "off"
          );
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function chooseResponseStyle(style: string) {
    if (style === responseStyle || styleStatus === "saving") return;
    const previous = responseStyle;
    setResponseStyle(style);
    setStyleStatus("saving");
    try {
      await updateResponseStyle(style);
      setStyleStatus("saved");
      setTimeout(() => setStyleStatus("idle"), 2500);
    } catch {
      setResponseStyle(previous);
      setStyleStatus("error");
      setTimeout(() => setStyleStatus("idle"), 4000);
    }
  }

  async function chooseVoiceReplies(tier: string) {
    if (tier === voiceReplies || voiceStatus === "saving") return;
    const previous = voiceReplies;
    setVoiceReplies(tier);
    setVoiceStatus("saving");
    try {
      await updateVoiceReplies(tier);
      setVoiceStatus("saved");
      setTimeout(() => setVoiceStatus("idle"), 2500);
    } catch {
      setVoiceReplies(previous);
      setVoiceStatus("error");
      setTimeout(() => setVoiceStatus("idle"), 4000);
    }
  }

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

  // Warm up the Meta SDK on mount (fire-and-forget): at click time only a
  // fast local fetch precedes FB.login, keeping it inside the browser's
  // user-gesture window so the popup isn't silently blocked.
  useEffect(() => {
    loadFacebookSdk()
      .then(() => setSdkLoading(false))
      .catch(() => setSdkLoading(false)); // click surfaces the real error
  }, []);

  // Defensive: if a provider's assets changed and picked points to missing assets, reset.
  useEffect(() => {
    const missing = Object.keys(picked).filter((k) => {
      const currentAssets = assets[k]?.map((a) => a.id) ?? [];
      return picked[k]?.some((id) => !currentAssets.includes(id));
    });
    if (missing.length > 0) {
      setPicked((prev) => {
        const updated = { ...prev };
        for (const k of missing) updated[k] = prev[k]?.filter((id) => (assets[k]?.map((a) => a.id) ?? []).includes(id)) ?? [];
        return updated;
      });
    }
  }, [assets]);

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

  const connectWhatsApp = async (mode: "standard" | "coexistence") => {
    // Meta's JS SDK hard-throws on non-HTTPS origins ("FB.login can no longer
    // be called from http pages"), which surfaces as a Next.js console-error
    // overlay and a dead popup. localhost is exempt; anything else needs TLS.
    const secure =
      window.location.protocol === "https:" ||
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";
    if (!secure) {
      onNotice(
        "err",
        "WhatsApp connect needs HTTPS — Facebook blocks Meta login on plain http. Open the app via localhost, or tunnel it (e.g. `ngrok http 3000`)."
      );
      return;
    }
    // Synchronous popup probe — runs inside the click gesture, before any
    // await. FB.login opens its popup after our awaits; if popups are
    // blocked its callback never fires and the button hangs on "…" forever.
    let probe: Window | null = null;
    try {
      probe = window.open("about:blank", "sayvors_popup_probe", "width=10,height=10");
    } catch {
      probe = null;
    }
    if (!probe || probe.closed) {
      onNotice("err", "Your browser blocked the Meta popup. Allow popups for this site, then click Connect again.");
      return;
    }
    try {
      probe.close();
    } catch {
      /* ignore */
    }
    setBusy("whatsapp");
    try {
      const entry = await startMetaConnect("whatsapp");
      if (!entry.fb_app_id || !entry.fb_config_id) {
        onNotice("err", "WhatsApp onboarding is not configured yet (META_WHATSAPP_CONFIG_ID).");
        setBusy(null);
        return;
      }
      let sdkOk = true;
      await loadFacebookSdk().catch((e: unknown) => {
        sdkOk = false;
        if (e instanceof Error && e.message === "SDK_BLOCKED") {
          onNotice(
            "err",
            "Your browser blocked the Meta SDK (ad-blocker / tracking prevention). Allow scripts from this site, then click Connect again."
          );
        } else {
          onNotice(
            "err",
            "The Meta SDK couldn't fully load — an ad-blocker or tracking protection may be blocking facebook.net. Allow it, then click Connect again."
          );
        }
        setBusy(null);
      });
      if (!sdkOk) return;
      if (!window.FB) {
        onNotice("err", "Could not load the Meta SDK. Check your connection and retry.");
        setBusy(null);
        return;
      }
      window.FB.init({ appId: entry.fb_app_id, version: entry.graph_api_version ?? "v26.0", xfbml: false });

      // Capture the Embedded Signup session payload (waba/phone/business ids).
      const session: Record<string, unknown> = {};
      const onSignupEvent = (resp: Record<string, unknown>) => {
        // Diagnostic: Meta reports wizard failures here too, with
        // data.error_message / data.error_type — the only place the
        // generic "Sorry, something went wrong" page explains itself.
        console.info("[Meta ES] session event", resp);
        const data = (resp.data ?? resp) as Record<string, unknown>;
        for (const k of ["waba_id", "phone_number_id", "business_id"]) {
          if (typeof data[k] === "string") session[k] = data[k];
        }
      };
      try {
        window.FB.Event?.subscribe("WA_EMBEDDED_SIGNUP", onSignupEvent);
        if (mode === "coexistence") {
          try {
            window.FB.Event?.subscribe(
              "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
              onSignupEvent
            );
          } catch { /* older SDK */ }
        }
      } catch {
        /* older SDK — continue without session capture */
      }

      // FB.login callback MUST be a plain function — the real SDK rejects
      // async callbacks ("Expression is of type asyncfunction, not function").
      const onLogin = async (loginResp: {
        authResponse?: { code?: string; accessToken?: string } | null;
        status?: string;
      }) => {
        // Diagnostic: see exactly what Meta handed back (code, error, cancel).
        console.info("[Meta ES] login response", loginResp);
        try {
          window.FB?.Event?.unsubscribe("WA_EMBEDDED_SIGNUP", onSignupEvent);
          if (mode === "coexistence") {
            try {
              window.FB?.Event?.unsubscribe(
                "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
                onSignupEvent
              );
            } catch { /* ignore */ }
          }
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
            pin: pinDraft || null,
            mode,
          });
          if (res.needs_pin) {
            // Connected, but the number cannot send until Meta has a 2-step
            // PIN. Say so plainly — a silent success here means every send
            // fails later and the cause is invisible. Remember which number
            // failed so the inline PIN prompt can retry just that one.
            const failedPhone = (res.registration_failed ?? []).find(
              (f) => f.asset_type === "phone_number"
            );
            setPendingReg(failedPhone?.asset_id ?? (session.phone_number_id as string) ?? null);
            onNotice(
              "err",
              "WhatsApp connected, but the number is NOT registered yet. Enter your 6-digit two-step verification PIN below to finish — without it the number cannot send messages."
            );
          } else {
            setPendingReg(null);
            if (mode === "coexistence") {
              onNotice(
                "ok",
                `WhatsApp connected (coexistence mode). Contact and history sync is in progress — this may take up to 24 hours.`
              );
            } else {
              onNotice(
                "ok",
                `WhatsApp connected and number registered! ${res.assets_found} asset(s) found — pick which number to use.`
              );
            }
          }
          setPicked((prev) => {
            const updated = { ...prev, ["whatsapp"]: [] };
            return updated;
          });
          setPicking("whatsapp");
          await refresh();
        } catch {
          onNotice("err", "WhatsApp session failed. Please try again.");
        } finally {
          setBusy(null);
        }
      };
      // v4 Tech Provider flow: Meta requires app_only_install extras with the
      // solution id. Plain Embedded Signup keeps the simpler extras shape.
      // Coexistence uses a different featureType.
      let extras: Record<string, unknown>;
      if (mode === "coexistence") {
        extras = {
          setup: {},
          featureType: "whatsapp_business_app_onboarding",
          sessionInfoVersion: "3",
        };
      } else if (entry.solution_id) {
        extras = {
          feature: "app_only_install",
          version: 4,
          sessionInfoVersion: 4,
          setup: { solutionID: entry.solution_id },
        };
      } else {
        extras = { setup: {}, sessionInfoVersion: "3" };
      }

      // v4 delivers the session payload as a window message as well — capture
      // both channels so waba/phone/business ids are never missed.
      const onSignupMessage = (event: MessageEvent) => {
        if (
          event.origin !== "https://www.facebook.com" &&
          event.origin !== "https://web.facebook.com"
        ) {
          return;
        }
        let data: { type?: string; data?: Record<string, unknown> } | null = null;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        if (data?.type !== "WA_EMBEDDED_SIGNUP") return;
        onSignupEvent(data.data ?? data);
      };
      window.addEventListener("message", onSignupMessage);

      // Coexistence uses its own Embedded Signup configuration: the merchant
      // keeps their number and their WhatsApp Business App, so Meta must not
      // show the new-number onboarding. Standard keeps the original config.
      const configId =
        mode === "coexistence"
          ? entry.fb_coexistence_config_id || entry.fb_config_id
          : entry.fb_config_id;

      console.log("=== WHATSAPP ONBOARDING DEBUG ===");
      console.log("mode:", mode);
      console.log("config_id:", configId);
      console.log("standard_config_id:", entry.fb_config_id);
      console.log("coexistence_config_id:", entry.fb_coexistence_config_id);
      console.log("solution_id:", entry.solution_id);
      console.log("extras:", JSON.stringify(extras, null, 2));

      window.FB.login(
        (loginResp) => {
          window.removeEventListener("message", onSignupMessage);
          void onLogin(loginResp);
        },
        {
          config_id: configId,
          response_type: "code",
          override_default_response_type: true,
          extras,
        }
      );
    } catch {
      onNotice("err", "Could not start WhatsApp connect.");
      setBusy(null);
    }
  };

  // Meta only permits /register for 14 days after signup, so a wrong or
  // missing PIN must be fixable WITHOUT a full Embedded Signup reconnect.
  const finishRegistration = async () => {
    if (!pendingReg) return;
    if (!/^\d{6}$/.test(pinDraft)) {
      onNotice("err", "Enter the 6-digit PIN from WhatsApp → Settings → Account → Two-step verification.");
      return;
    }
    setBusy("whatsapp-reg");
    try {
      await registerWhatsAppNumber(pendingReg, pinDraft);
      setPinDraft("");
      setPendingReg(null);
      onNotice("ok", "Number registered — WhatsApp can send now.");
      await refresh();
    } catch {
      onNotice("err", "Registration rejected. Check the PIN and try again (you have 14 days from signup).");
    } finally {
      setBusy(null);
    }
  };

  const savePick = async (provider: MetaProvider) => {
    const providerPicked = picked[provider] ?? [];
    if (providerPicked.length === 0) return;
    setBusy(`${provider}-save`);
    try {
      await selectMetaAssets(provider, providerPicked);
      onNotice("ok", `${provider} asset(s) activated.`);
      setPicking(null);
      setPicked((prev) => ({ ...prev, [provider]: [] }));
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

  const disconnect = async (provider: MetaProvider, deleteData: boolean) => {
    setBusy(`${provider}-off`);
    try {
      await disconnectMeta(provider, { deleteData });
      onNotice(
        "ok",
        deleteData
          ? `${provider} disconnected — all data deleted.`
          : `${provider} disconnected. Your messages are kept.`,
      );
      setConfirmOff(null);
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
      setPicked((prev) => ({ ...prev, ["instagram"]: [] }));
      setPicking("instagram");
      await refresh();
    } catch (e) {
      onNotice("err", e instanceof Error ? e.message : "Connect Facebook first, then discover Instagram.");
    } finally {
      setBusy(null);
    }
  };

  const providersToShow = activeFilter ? PROVIDERS.filter((p) => p.key === activeFilter) : PROVIDERS;

  return (
    <div className="space-y-3">
      {/* Provider sub-tabs (light design — best UX with per-provider theme) */}
      {!activeFilter && (
        <div className="flex gap-1.5 overflow-x-auto rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
          {PROVIDERS.map((p) => {
            const hasActive = connections[p.key]?.status === "active";
            return (
              <a
                key={p.key}
                href={`?provider=${p.key}`}
                className={`flex-1 whitespace-nowrap rounded-lg px-3 py-2 text-[11px] font-semibold transition
                  ${p.key === "whatsapp" ? "hover:bg-emerald-500/10 hover:text-emerald-700" : p.key === "facebook" ? "hover:bg-blue-500/10 hover:text-blue-700" : p.key === "instagram" ? "hover:bg-pink-500/10 hover:text-pink-700" : "hover:bg-ink/[0.04] hover:text-ink/70"}
                  ${hasActive ? `text-ink dark:text-fog shadow-sm ring-1 ring-ink/[0.04] dark:ring-fog/[0.08]` : "text-ink/35 dark:text-fog/30"}`}
              >
                <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${p.color.replace("from-", "bg-").replace(" to-", "") || p.color}`} />
                {p.name}
              </a>
            );
          })}
        </div>
      )}
      <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
        Meta — your own business accounts {activeFilter ? `· ${PROVIDERS.find((p) => p.key === activeFilter)?.name}` : ""}
      </p>
      {providersToShow.map((p) => {
        const conn = connections[p.key];
        const list = assets[p.key] ?? [];
        // WhatsApp's WABA rows are infrastructure (webhook subscription, done
        // automatically post-signup) — a tenant picks a phone number, never a
        // container. Offering both is how the picker read as duplicates.
        const pickerList =
          p.key === "whatsapp" ? list.filter((a) => a.asset_type === "phone_number") : list;
        // The card summarizes what actually serves the user. For WhatsApp that
        // is the phone numbers — listing the WABA container too produced
        // "Test number +15556259436, BM, BM", three names for one number.
        const active = list.filter(
          (a) => a.active && (p.key !== "whatsapp" || a.asset_type === "phone_number"),
        );
        const label =
          active.length > 0
            ? active
                .map(
                  (a) =>
                    (p.key === "whatsapp"
                      ? a.phone ?? a.name
                      : a.name ?? a.username ?? a.phone) ?? a.external_asset_id,
                )
                .join(", ")
            : conn && conn.status !== "revoked"
              ? `Connected (${conn.status})`
              : p.blurb;
        // A revoked connection is fully disconnected (token wiped server-side);
        // show the Connect entry again instead of manage buttons.
        const isDisconnected = !conn || conn.status === "revoked";
        return (
          <div key={p.key}>
            <div
              className={`flex flex-wrap items-center gap-4 rounded-xl border bg-white p-4 transition dark:bg-ink ${
                activeFilter ? p.key === "whatsapp" ? "border-emerald-200/60 shadow-[0_0_28px_-8px_rgba(16,185,129,0.25)] dark:border-emerald-500/20" : p.key === "facebook" ? "border-blue-200/60 shadow-[0_0_28px_-8px_rgba(37,99,235,0.25)] dark:border-blue-500/20" : p.key === "instagram" ? "border-pink-200/60 shadow-[0_0_28px_-8px_rgba(236,72,153,0.25)] dark:border-pink-500/20" : "border-ink/[0.06] dark:border-fog/[0.06]" : "border-ink/[0.06] dark:border-fog/[0.06]"
              }`}
            >
              <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${p.color} text-[22px] text-white shadow-sm`}>
                {p.icon}
              </div>
              <div className="min-w-0 flex-1 sm:min-w-[10rem]">
                <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[14px] font-semibold text-ink dark:text-fog">
                  {p.name}
                  {conn && conn.status !== "revoked" && (
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
              {isDisconnected ? (
                <>
                  <div className="flex shrink-0 items-center gap-2 max-sm:w-full">
                    {p.key === "whatsapp" ? (
                      <>
                        <button
                          onClick={() => { setWaMode("standard"); connectWhatsApp("standard"); }}
                          disabled={busy === "whatsapp" || sdkLoading}
                          className="min-h-8 rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                        >
                          {busy === "whatsapp" && waMode === "standard" ? "…" : "Create new"}
                        </button>
                        <button
                          onClick={() => { setWaMode("coexistence"); connectWhatsApp("coexistence"); }}
                          disabled={busy === "whatsapp" || sdkLoading}
                          className="min-h-8 rounded-lg border border-deep-violet/30 px-3.5 py-1.5 text-[12px] font-semibold text-deep-violet transition hover:bg-deep-violet/10 disabled:opacity-50"
                        >
                          {busy === "whatsapp" && waMode === "coexistence" ? "…" : "Connect existing"}
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => connectOAuth(p.key)}
                        disabled={busy === p.key}
                        className="min-h-8 rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                      >
                        {busy === p.key ? "…" : "Connect"}
                      </button>
                    )}
                  </div>
                  {p.key === "whatsapp" && (
                    <p className="text-[10px] text-ink/30 dark:text-fog/30 mt-1">
                      &ldquo;Create new&rdquo; registers a fresh number. &ldquo;Connect existing&rdquo; links a number already active on the WhatsApp Business app.
                    </p>
                  )}
                </>
              ) : (
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    onClick={() => {
                      const current = (assets[p.key] ?? []).filter((a) => a.active).map((a) => a.id);
                      setPicked((prev) => ({ ...prev, [p.key]: current }));
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
                    onClick={() => { setConfirmOff(p.key); setWipeData(false); }}
                    disabled={busy === `${p.key}-off`}
                    className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-red-600 transition hover:bg-red-500/10 disabled:opacity-50"
                  >
                    Disconnect
                  </button>
                </div>
              )}
            </div>

            {/* Registration follow-up: only after a connect that returned
                needs_pin, never before the tenant has a number at all. */}
            {p.key === "whatsapp" && pendingReg && (
              <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-3">
                <label className="sr-only" htmlFor="wa-2sv-pin">
                  WhatsApp two-step verification PIN
                </label>
                <input
                  id="wa-2sv-pin"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={pinDraft}
                  onChange={(e) => setPinDraft(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="6-digit PIN"
                  title="Your 6-digit WhatsApp two-step verification PIN. Needed for Meta to register the number."
                  className="w-28 rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[12px] tabular-nums outline-none focus:border-deep-violet/30 dark:border-fog/[0.1] dark:bg-ink"
                />
                <button
                  onClick={finishRegistration}
                  disabled={busy === "whatsapp-reg" || pinDraft.length !== 6}
                  className="rounded-lg bg-deep-violet px-3 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  {busy === "whatsapp-reg" ? "Registering…" : "Finish registration"}
                </button>
                <span className="text-[11px] text-ink/50 dark:text-fog/50">
                  WhatsApp → Settings → Account → Two-step verification
                </span>
              </div>
            )}

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
                {pickerList.length === 0 && <p className="text-[12px] text-ink/40">No assets found yet — connect again or retry.</p>}
                {pickerList.map((a) => (
                  <label key={a.id} className="flex cursor-pointer flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12px]">
                    <input
                      type="checkbox"
                      checked={(picked[p.key] ?? []).includes(a.id)}
                      onChange={() => {
                        const current = picked[p.key] ?? [];
                        const updated = current.includes(a.id)
                          ? current.filter((x) => x !== a.id)
                          : [...current, a.id];
                        setPicked((prev) => ({ ...prev, [p.key]: updated }));
                      }}
                      className="h-4 w-4 shrink-0 accent-[#5b2d8e]"
                    />
                    <span className="min-w-0 break-words font-semibold">
                      {assetLabel(a)}
                    </span>
                    <span className="min-w-0 break-words text-ink/40">
                      {a.asset_type}
                      {a.status !== "connected" ? ` · ${a.status}` : ""}
                      {a.active ? " · active" : ""}
                    </span>
                  </label>
                ))}
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => savePick(p.key)}
                    disabled={(picked[p.key] ?? []).length === 0 || busy === `${p.key}-save`}
                    className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                  >
                    {busy === `${p.key}-save` ? "Saving…" : `Use selected (${(picked[p.key] ?? []).length})`}
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

            {/* Response style — how the AI's replies are delivered on WhatsApp.
                Saved per account; takes effect for messages sent after the save. */}
            {p.key === "whatsapp" && conn && conn.status !== "revoked" && (
              <div className="mt-2 rounded-xl border border-ink/[0.06] bg-white/70 p-3 dark:border-fog/[0.06] dark:bg-ink/60">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[12px] font-semibold text-ink dark:text-fog">Response style</p>
                  {styleStatus === "saving" && (
                    <span className="text-[11px] text-ink/40 dark:text-fog/40">Saving&hellip;</span>
                  )}
                  {styleStatus === "saved" && (
                    <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                      Saved &mdash; applies to new messages
                    </span>
                  )}
                  {styleStatus === "error" && (
                    <span className="text-[11px] font-semibold text-red-600 dark:text-red-400">
                      Couldn&rsquo;t save &mdash; try again
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">
                  How the AI&rsquo;s replies are delivered to customers on WhatsApp.
                </p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {RESPONSE_STYLE_OPTIONS.map((opt) => {
                    const selected = responseStyle === opt.value;
                    return (
                      <button
                        key={opt.value}
                        onClick={() => chooseResponseStyle(opt.value)}
                        disabled={styleStatus === "saving"}
                        aria-pressed={selected}
                        className={`rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
                          selected
                            ? "border-deep-violet/40 bg-deep-violet/[0.06]"
                            : "border-ink/[0.08] hover:border-deep-violet/25 dark:border-fog/[0.1]"
                        }`}
                      >
                        <span className="block text-[12px] font-semibold text-ink dark:text-fog">{opt.label}</span>
                        <span className="mt-0.5 block text-[11px] text-ink/45 dark:text-fog/45">{opt.desc}</span>
                      </button>
                    );
                  })}
                </div>
                {responseStyle === "human" && (
                  <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-[11px] leading-relaxed text-amber-700 dark:border-amber-500/20 dark:text-amber-300">
                    ⚠️ Human-like responses may send multiple WhatsApp messages for a single response, which can increase WhatsApp messaging usage and costs.
                  </div>
                )}
              </div>
            )}

            {/* Voice replies — when a customer seems confused, the AI follows
                up with a short voice note in the customer's own language.
                Tier is a tenant choice; the engine behind each tier is
                managed by the admins. */}
            {p.key === "whatsapp" && conn && conn.status !== "revoked" && (
              <div className="mt-2 rounded-xl border border-ink/[0.06] bg-white/70 p-3 dark:border-fog/[0.06] dark:bg-ink/60">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[12px] font-semibold text-ink dark:text-fog">Voice replies</p>
                  {voiceStatus === "saving" && (
                    <span className="text-[11px] text-ink/40 dark:text-fog/40">Saving&hellip;</span>
                  )}
                  {voiceStatus === "saved" && (
                    <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                      Saved &mdash; applies to new messages
                    </span>
                  )}
                  {voiceStatus === "error" && (
                    <span className="text-[11px] font-semibold text-red-600 dark:text-red-400">
                      Couldn&rsquo;t save &mdash; try again
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">
                  When a customer seems confused, the AI can follow up with a short voice note in their own language.
                </p>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {VOICE_REPLY_OPTIONS.map((opt) => {
                    const selected = voiceReplies === opt.value;
                    return (
                      <button
                        key={opt.value}
                        onClick={() => chooseVoiceReplies(opt.value)}
                        disabled={voiceStatus === "saving"}
                        aria-pressed={selected}
                        className={`rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
                          selected
                            ? "border-deep-violet/40 bg-deep-violet/[0.06]"
                            : "border-ink/[0.08] hover:border-deep-violet/25 dark:border-fog/[0.1]"
                        }`}
                      >
                        <span className="block text-[12px] font-semibold text-ink dark:text-fog">{opt.label}</span>
                        <span className="mt-0.5 block text-[11px] text-ink/45 dark:text-fog/45">{opt.desc}</span>
                      </button>
                    );
                  })}
                </div>
                {voiceReplies !== "off" && (
                  <p className="mt-2 text-[11px] leading-relaxed text-ink/40 dark:text-fog/40">
                    Voice notes are short (about 30&ndash;40 seconds) and sent at most once per reply. If a voice can&rsquo;t be produced, the customer gets the text reply instead.
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}

      {/* Disconnect confirmation: soft disconnect keeps history, the wipe
          option deletes everything so a reconnect starts from scratch. */}
      {confirmOff && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={(e) => { if (e.target === e.currentTarget) setConfirmOff(null); }}
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-xl dark:border-fog/[0.08] dark:bg-ink">
            <p className="text-[15px] font-bold text-ink dark:text-fog">
              Disconnect {PROVIDERS.find((x) => x.key === confirmOff)?.name}?
            </p>
            <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-[12px] text-ink/70 dark:text-fog/70">
              <input
                type="checkbox"
                checked={wipeData}
                onChange={(e) => setWipeData(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[#5b2d8e]"
              />
              <span>
                Also permanently delete all data — conversations, messages, channels and assets.
                <span className="mt-1 block text-ink/45 dark:text-fog/45">
                  If you connect again you start from scratch, as if you were never connected.
                  This cannot be undone.
                </span>
              </span>
            </label>
            <p className="mt-2 text-[11px] text-ink/40 dark:text-fog/40">
              Leave it unchecked to disconnect only — your history stays and is here when you
              reconnect.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirmOff(null)}
                className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-ink/50 transition hover:bg-ink/[0.04] dark:text-fog/50"
              >
                Cancel
              </button>
              <button
                onClick={() => void disconnect(confirmOff, wipeData)}
                disabled={busy === `${confirmOff}-off`}
                className={`rounded-lg px-3.5 py-1.5 text-[12px] font-semibold text-white transition disabled:opacity-50 ${
                  wipeData ? "bg-red-600 hover:bg-red-700" : "bg-deep-violet hover:opacity-90"
                }`}
              >
                {busy === `${confirmOff}-off`
                  ? "…"
                  : wipeData
                    ? "Disconnect & delete everything"
                    : "Disconnect"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
