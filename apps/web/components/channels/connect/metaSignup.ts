"use client";

/**
 * Meta signup primitives shared by the channel onboarding screens.
 *
 * Both the Facebook/Instagram OAuth hand-off and the WhatsApp Embedded
 * Signup must be started from a real user gesture: the browser only allows
 * the popup while the click is being processed. Everything here is written
 * around that constraint — the synchronous popup probe runs before the
 * first `await`, and the SDK is warmed on page mount so the click path is
 * only a fast local fetch.
 */

import { postWhatsAppSession, startMetaConnect, type MetaProvider } from "@/lib/api-meta";

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

// Same-origin proxy (backend /api/v1/meta/connect-sdk): ad-blockers match the
// facebook.net domain and common SDK filenames — this route has neither.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FB_SDK_SRC = `${API_BASE}/api/v1/meta/connect-sdk`;

// sdk.js is a 12KB bootstrap that defines a STUB window.FB immediately
// (init/login/Event all exist but only buffer calls) and loads the real
// 272KB bundle from connect.facebook.net afterwards. So "FB.init exists" is
// NOT a readiness signal — the stub satisfies it. The real bundle fires
// window.fbAsyncInit when ready; key readiness on that. Calling FB.login
// against the stub buffers the call and replays it outside the click gesture
// (or never, if facebook.net is blocked) — which is how the Meta popup gets
// silently blocked.
let sdkPromise: Promise<void> | null = null;
let sdkReady = false;

export function loadFacebookSdk(): Promise<void> {
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
    window.fbAsyncInit = () => {
      clearTimeout(deadline);
      done();
    };
    if (document.getElementById("facebook-jssdk")) return;
    const s = document.createElement("script");
    s.id = "facebook-jssdk";
    s.src = FB_SDK_SRC;
    s.async = true;
    s.onerror = () => {
      clearTimeout(deadline);
      fail("SDK_BLOCKED");
    };
    document.head.appendChild(s);
  });
  return sdkPromise;
}

/** Warm the SDK on mount so the Connect click only waits on a local fetch. */
export function warmFacebookSdk(): void {
  void loadFacebookSdk().catch(() => {
    /* the click surfaces the real error */
  });
}

export type WhatsAppMode = "standard" | "coexistence";

export interface WhatsAppSignupResult {
  state: string;
  mode: WhatsAppMode;
  assetsFound: number;
  /** The number exists in Sayvors but Meta refused to register it. */
  needsPin: boolean;
  /** phone_number_id awaiting a 6-digit PIN, when `needsPin` is true. */
  pendingRegistrationId: string | null;
  registrationFailed: { asset_id: string; asset_type: string; status: number }[];
}

function assertSecureOrigin(): void {
  // Meta's JS SDK hard-throws on non-HTTPS origins ("FB.login can no longer
  // be called from http pages"), which surfaces as a Next.js console-error
  // overlay and a dead popup. localhost is exempt; anything else needs TLS.
  const secure =
    window.location.protocol === "https:" ||
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  if (!secure) {
    throw new Error(
      "WhatsApp connect needs HTTPS — Facebook blocks Meta login on plain http. Open the app via localhost, or tunnel it (e.g. `ngrok http 3000`)."
    );
  }
}

function assertPopupAllowed(): void {
  // Synchronous probe: FB.login opens its popup after our awaits; if popups
  // are blocked its callback never fires and the button hangs forever.
  let probe: Window | null = null;
  try {
    probe = window.open("about:blank", "sayvors_popup_probe", "width=10,height=10");
  } catch {
    probe = null;
  }
  if (!probe || probe.closed) {
    throw new Error(
      "Your browser blocked the Meta popup. Allow popups for this site, then try again."
    );
  }
  try {
    probe.close();
  } catch {
    /* ignore */
  }
}

/**
 * Run Meta's WhatsApp Embedded Signup and persist the resulting session.
 *
 * MUST be called directly from a click handler — it opens a popup before its
 * first `await`. Throws `Error` with a message that is safe to show as-is.
 */
export async function runWhatsAppSignup(mode: WhatsAppMode): Promise<WhatsAppSignupResult> {
  assertSecureOrigin();
  assertPopupAllowed();

  const entry = await startMetaConnect("whatsapp", {
    next: "/dashboard/channels/whatsapp/connect",
  });
  if (!entry.fb_app_id || !entry.fb_config_id) {
    throw new Error("WhatsApp onboarding is not configured yet (META_WHATSAPP_CONFIG_ID).");
  }

  try {
    await loadFacebookSdk();
  } catch (e) {
    if (e instanceof Error && e.message === "SDK_BLOCKED") {
      throw new Error(
        "Your browser blocked the Meta SDK (ad-blocker / tracking prevention). Allow scripts from this site, then try again."
      );
    }
    throw new Error(
      "The Meta SDK couldn't fully load — an ad-blocker or tracking protection may be blocking facebook.net. Allow it, then try again."
    );
  }
  if (!window.FB) {
    throw new Error("Could not load the Meta SDK. Check your connection and retry.");
  }

  window.FB.init({
    appId: entry.fb_app_id,
    version: entry.graph_api_version ?? "v26.0",
    xfbml: false,
  });

  // Capture the Embedded Signup session payload (waba/phone/business ids).
  const session: Record<string, unknown> = {};
  const onSignupEvent = (resp: Record<string, unknown>) => {
    const data = (resp.data ?? resp) as Record<string, unknown>;
    for (const k of ["waba_id", "phone_number_id", "business_id"]) {
      if (typeof data[k] === "string") session[k] = data[k];
    }
  };

  const cleanup = () => {
    try {
      window.FB?.Event?.unsubscribe("WA_EMBEDDED_SIGNUP", onSignupEvent);
      if (mode === "coexistence") {
        window.FB?.Event?.unsubscribe(
          "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
          onSignupEvent
        );
      }
    } catch {
      /* older SDK */
    }
    window.removeEventListener("message", onSignupMessage);
  };

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

  try {
    window.FB.Event?.subscribe("WA_EMBEDDED_SIGNUP", onSignupEvent);
    if (mode === "coexistence") {
      window.FB.Event?.subscribe("FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", onSignupEvent);
    }
  } catch {
    /* older SDK — continue without session capture */
  }
  window.addEventListener("message", onSignupMessage);

  const loginResp = await new Promise<{
    authResponse?: { code?: string; accessToken?: string } | null;
    status?: string;
  }>((resolve) => {
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

    // Coexistence uses its own Embedded Signup configuration: the merchant
    // keeps their number and their WhatsApp Business App, so Meta must not
    // show the new-number onboarding.
    const configId =
      mode === "coexistence"
        ? entry.fb_coexistence_config_id || entry.fb_config_id
        : entry.fb_config_id;

    // FB.login's callback MUST be a plain function — the real SDK rejects
    // async callbacks ("Expression is of type asyncfunction, not function").
    window.FB!.login((resp) => resolve(resp), {
      config_id: configId,
      response_type: "code",
      override_default_response_type: true,
      extras,
    });
  });

  cleanup();

  const code = loginResp?.authResponse?.code ?? null;
  if (!code && Object.keys(session).length === 0) {
    throw new Error("WhatsApp onboarding was cancelled.");
  }

  const res = await postWhatsAppSession({
    state: entry.state,
    code,
    waba_id: (session.waba_id as string) ?? null,
    phone_number_id: (session.phone_number_id as string) ?? null,
    business_id: (session.business_id as string) ?? null,
    mode,
  });

  const failedPhone = (res.registration_failed ?? []).find(
    (f) => f.asset_type === "phone_number"
  );

  return {
    state: entry.state,
    mode,
    assetsFound: res.assets_found,
    needsPin: Boolean(res.needs_pin),
    pendingRegistrationId: res.needs_pin
      ? failedPhone?.asset_id ?? (session.phone_number_id as string) ?? null
      : null,
    registrationFailed: res.registration_failed ?? [],
  };
}

/**
 * Start the Facebook / Instagram OAuth hand-off.
 *
 * `nextPath` brings the tenant back to the onboarding screen they started
 * from instead of the generic channels page.
 */
export async function startMetaOAuth(provider: MetaProvider, nextPath: string): Promise<void> {
  const entry = await startMetaConnect(provider, { next: nextPath });
  if (!entry.auth_url) {
    throw new Error(`${provider} connect is not configured yet.`);
  }
  window.location.href = entry.auth_url;
}
