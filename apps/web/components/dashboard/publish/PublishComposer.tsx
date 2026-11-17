"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { INK, INK2 } from "@/components/channels/instagram/ui";
import { apiFetch } from "@/lib/api-rag";
import { externalAssetIdFor } from "@/lib/publish-targets";
import { checkWindow, minLocalInput } from "@/lib/publish-schedule";
import { cropSignature, exportCroppedImage } from "@/lib/crop-image";
import MediaSink from "./MediaSink";
import DestinationSelector from "./DestinationSelector";
import DestinationPreview from "./DestinationPreview";
import ConfirmModal from "./ConfirmModal";
import CropFrame from "./CropFrame";
import FormatThumb from "./FormatThumb";
import {
  DEFAULT_CROP,
  GALLERY_CATEGORIES,
  GOOGLE_POST_LANGUAGE,
  METHOD_META,
  PLATFORM_META,
  cropKeyFor,
  defaultCropFor,
  isFeedMethod,
  methodsFor,
  type CropState,
  type MediaState,
  type PostMethod,
  type PublishTarget,
} from "./types";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

/**
 * A short stable token for a request group, used as the idempotency suffix.
 *
 * The group is identified by its crop. A crop signature can reach 364
 * characters while the publish API caps `idempotency_key` at 200, so the raw
 * group key cannot be sent. FNV-1a is deterministic, so a retry of the same
 * draft produces the same token and the backend still collapses it onto the
 * earlier job. Two different groups can only collide on the same
 * platform/asset/method if they are the same request, so a collision cannot
 * drop a destination.
 */
function groupToken(key: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i += 1) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

type MethodDict = Dict["publish"]["methods"];
type ComposerDict = Dict["publish"]["composer"];

/** Formats that cannot be published without an image. Google updates and
 * Meta feed posts allow text-only; gallery, profile and banner (shown as
 * Promotion) are image surfaces. */
const MEDIA_ONLY_METHODS = new Set<string>([
  "story", "reel", "status", "gallery", "profile", "banner",
]);

type CtaValue = "book" | "order" | "shop" | "learn_more" | "sign_up" | "call";
const CTA_VALUES: CtaValue[] = [
  "book", "order", "shop", "learn_more", "sign_up", "call",
];

/*
 * The unified Publish composer.
 *
 * A 3-step wizard (Media & message → Destinations → When & publish) keeps
 * every section mounted — steps are toggled with `hidden` — so no draft
 * state, media preview or open modal is lost while navigating.
 *
 * Confirming uploads locally-picked media to /api/v1/media/upload (the
 * provider must fetch the files from a public URL at publish time), then
 * creates one job per destination+format via POST /api/v1/channels/publish.
 * A locally-picked file that never uploads means the post never leaves,
 * so only https URLs and stored files make it through the confirm gate.
 */

const FIELD =
  "clay-input px-3.5 py-2.5 text-[13px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]";

// ── AI video creator (UI-only, HTML-based, no backend) ─────────────────
function sanitizeName(s: string): string {
  return s.replace(/[^a-z0-9-_]+/gi, "-").replace(/^-+|-+$/g, "") || "business";
}

function buildVideoHtml(opts: { business: string; primary: string; accent: string; bg: string }): string {
  const { business, primary, accent, bg } = opts;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1920,height=1080" />
<title>${business} — launch video</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{width:1920px;height:1080px;overflow:hidden;background:${bg};font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:${primary}}
  .stage{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px}
  .glow{position:absolute;border-radius:50%;filter:blur(60px);pointer-events:none}
  .name{font-size:150px;font-weight:900;letter-spacing:-0.04em;line-height:1;opacity:0;transform:scale(0.85);animation:nameIn 1.2s 0.3s cubic-bezier(.2,.8,.2,1) forwards}
  .tag{font-size:42px;font-weight:400;color:${accent};opacity:0;transform:translateY(24px);animation:tagIn 0.9s 1.1s ease-out forwards}
  .sub{font-size:22px;color:${primary};opacity:0.6;letter-spacing:0.18em;text-transform:uppercase;font-weight:600;opacity:0;animation:subIn 0.8s 1.6s ease-out forwards}
  @keyframes nameIn{to{opacity:1;transform:scale(1)}}
  @keyframes tagIn{to{opacity:1;transform:translateY(0)}}
  @keyframes subIn{to{opacity:0.6}}
  .ring{position:absolute;width:600px;height:600px;border-radius:50%;border:2px solid ${primary};opacity:0.12;animation:pulse 3s ease-in-out infinite}
  @keyframes pulse{0%,100%{transform:scale(1);opacity:0.12}50%{transform:scale(1.15);opacity:0.06}}
</style>
</head>
<body>
  <div class="stage">
    <div class="glow ring" style="top:50%;left:50%;transform:translate(-50%,-50%)"></div>
    <div class="glow ring" style="top:50%;left:50%;transform:translate(-50%,-50%);animation-delay:1s;width:900px;height:900px"></div>
    <p class="sub">${business}</p>
    <h1 class="name">${business}.</h1>
    <p class="tag">AI that runs your merchant's online presence.</p>
  </div>
</body>
</html>`;
}

function AiVideoCreator({ googleTargets }: { googleTargets: PublishTarget[] }) {
  const { t, locale } = useI18n();
  const pc = t.publish.composer;
  const businessOptions = useMemo(() => {
    const names = new Set<string>();
    googleTargets.forEach((t) => names.add(t.name));
    if (names.size === 0) names.add("My Business");
    return [...names];
  }, [googleTargets]);

  const [business, setBusiness] = useState(businessOptions[0] ?? "My Business");
  const [primary, setPrimary] = useState("#3d1d6e");
  const [accent, setAccent] = useState("#b0338a");
  const [bg, setBg] = useState("#f4f2f7");
  const [html, setHtml] = useState<string | null>(null);
  const [generated, setGenerated] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const fileName = `${sanitizeName(business)}.mp4`;

  const generate = () => {
    const h = buildVideoHtml({ business, primary, accent, bg });
    setHtml(h);
    setGenerated(true);
    // reload iframe to replay
    if (iframeRef.current) {
      iframeRef.current.srcdoc = h;
    }
  };

  return (
    <div className="space-y-3">
      {/* business selector */}
      <div>
        <label className={`block text-[11px] font-semibold ${INK2} mb-1`}>{pc.aiBusiness}</label>
        <select
          value={business}
          onChange={(e) => setBusiness(e.target.value)}
          className="w-full clay-input px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
        >
          {businessOptions.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>
        {businessOptions.length <= 1 && (
          <input
            type="text"
            value={business}
            onChange={(e) => setBusiness(e.target.value)}
            placeholder={pc.aiBusinessPh}
            className="mt-2 w-full clay-input px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
          />
        )}
      </div>

      {/* color branding */}
      <div>
        <label className={`block text-[11px] font-semibold ${INK2} mb-1`}>{pc.aiColors}</label>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <span className={`block text-[10px] ${INK2} mb-1`}>{pc.aiPrimary}</span>
            <input type="color" value={primary} onChange={(e) => setPrimary(e.target.value)}
              className="h-9 w-full cursor-pointer rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)]" />
          </div>
          <div>
            <span className={`block text-[10px] ${INK2} mb-1`}>{pc.aiAccent}</span>
            <input type="color" value={accent} onChange={(e) => setAccent(e.target.value)}
              className="h-9 w-full cursor-pointer rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)]" />
          </div>
          <div>
            <span className={`block text-[10px] ${INK2} mb-1`}>{pc.aiBg}</span>
            <input type="color" value={bg} onChange={(e) => setBg(e.target.value)}
              className="h-9 w-full cursor-pointer rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)]" />
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[
            { p: "#3d1d6e", a: "#b0338a", b: "#f4f2f7" },
            { p: "#14101f", a: "#ff4f6e", b: "#f4f2f7" },
            { p: "#0f766e", a: "#14b8a6", b: "#f0fdfa" },
            { p: "#1e3a8a", a: "#3b82f6", b: "#eff6ff" },
          ].map((preset, i) => (
            <button
              key={i}
              type="button"
              onClick={() => { setPrimary(preset.p); setAccent(preset.a); setBg(preset.b); }}
              className="h-6 w-6 rounded-full border border-[var(--ui-line)]"
              style={{ background: `linear-gradient(135deg, ${preset.p}, ${preset.a})` }}
              title={pc.aiPreset}
            />
          ))}
        </div>
      </div>

      {/* file name */}
      <div className={`rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-2 text-[11px] ${INK2}`}>
        {fill(pc.aiFile, { name: fileName })}
      </div>

      {/* actions */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={generate}
          className="w-full clay-btn-primary px-3 py-2 text-[12px] font-bold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        >
          {pc.aiCreate}
        </button>
      </div>

      {/* video player / preview */}
      <div className="overflow-hidden rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-sunken)]">
        <div className="flex items-center gap-2 border-b border-[var(--ui-line)] px-3 py-2">
          <span className={`text-[11px] font-bold uppercase tracking-widest ${INK2}`}>{pc.aiPreview}</span>
          <span className={`ml-auto text-[10px] ${INK2}`}>{generated ? pc.aiReady : pc.aiEmpty}</span>
        </div>
        <div className="relative" style={{ aspectRatio: "16 / 9" }}>
          {html ? (
            <iframe
              ref={iframeRef}
              srcDoc={html}
              title={`${business} video preview`}
              className="absolute inset-0 h-full w-full border-0"
              sandbox="allow-scripts"
            />
          ) : (
            <div className={`absolute inset-0 flex flex-col items-center justify-center gap-2 ${INK2}`}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                <rect x="3" y="5" width="18" height="14" rx="2" />
                <path d="M10 9l5 3-5 3V9z" fill="currentColor" stroke="none" />
              </svg>
              <span className="text-[12px] font-medium">{pc.aiEmptyCta}</span>
            </div>
          )}
        </div>
        {generated && (
          <div className="flex items-center justify-between border-t border-[var(--ui-line)] px-3 py-2">
            <span className={`text-[11px] ${INK2}`}>{pc.aiNote}</span>
            <button
              type="button"
              onClick={() => { if (iframeRef.current && html) iframeRef.current.srcdoc = html; }}
              className={`text-[11px] font-semibold ${INK} hover:underline`}
            >
              {pc.aiReplay}
            </button>
          </div>
        )}
      </div>

      {/* publish video — coming soon */}
      <button
        type="button"
        disabled
        title={fill(pc.aiPublishSoonTitle, { name: business })}
        className="w-full rounded-[16px] border border-dashed border-[var(--ui-line-strong)] bg-[var(--ui-sunken)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink-2)] opacity-60 cursor-not-allowed"
      >
        {pc.aiPublishSoon}
      </button>
    </div>
  );
}

export default function PublishComposer({
  onPublished,
  onCancel,
  onNotice,
  initialScheduleDate,
}: {
  onPublished?: () => void;
  onCancel?: () => void;
  /**
   * Told about anything the merchant must know after a successful publish -
   * today, that Google filed a photo under a different category. The composer
   * closes on success, so the message has to travel to the page that opened
   * it, otherwise it is never seen.
   */
  onNotice?: (text: string) => void;
  initialScheduleDate?: string | null;
}) {
  // ── Destinations ─────────────────────────────────────────────────
  const [targets, setTargets] = useState<PublishTarget[]>([]);
  const [googleTargets, setGoogleTargets] = useState<PublishTarget[]>([]);
  const [targetsStatus, setTargetsStatus] = useState<"loading" | "ready">("loading");
  const [allConnected, setAllConnected] = useState(false);
  const [allGoogleConnected, setAllGoogleConnected] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { fetchPublishTargets } = await import("@/lib/publish-targets");
      const set = await fetchPublishTargets();
      if (cancelled) return;
      setTargets(set.social);
      setGoogleTargets(set.google);
      setTargetsStatus("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const usableTargets = useMemo(() => targets.filter((t) => !t.demo), [targets]);
  const usableGoogleTargets = useMemo(() => googleTargets.filter((t) => !t.demo), [googleTargets]);
  const selectedTargets = useMemo(
    () => [...targets.filter((t) => selected.has(t.id)), ...googleTargets.filter((t) => selected.has(t.id))],
    [targets, googleTargets, selected],
  );
  // Several branches of the same platform share one format panel and one
  // configuration: selecting a format or a gallery category is entered once
  // and written to every selected branch.
  const sharedMode =
    selectedTargets.length > 1 &&
    selectedTargets.every((t) => t.platform === selectedTargets[0].platform);

  // ── Media + message ─────────────────────────────────────────────
  const [media, setMedia] = useState<MediaState | null>(null);
  const [caption, setCaption] = useState("");
  const [description, setDescription] = useState("");
  const [ctaType, setCtaType] = useState("");
  const [ctaUrl, setCtaUrl] = useState("");

  const blobRef = useRef<string | null>(null);

  // ── Publishing ──────────────────────────────────────────────────
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  /** Description drafting state, local so a retry never loses the draft. */
  const [descDrafting, setDescDrafting] = useState(false);
  const [descNotice, setDescNotice] = useState<{ kind: "ok" | "err" | "info"; text: string } | null>(null);
  /**
   * The current publish attempt of this draft. The key stays the same
   * across retries so a partial failure cannot publish the same post twice;
   * galleryDone records the locations that already received the photo.
   */
  const publishAttemptRef = useRef<{ key: string; galleryDone: Set<string> } | null>(null);
  /** Notices about photos Google filed under a different category. */
  const [galleryFallbacks, setGalleryFallbacks] = useState<string[]>([]);

  // ── Schedule ────────────────────────────────────────────────────
  const [scheduleOn, setScheduleOn] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");

  // Pre-fill schedule when navigated from the calendar with a date.
  useEffect(() => {
    if (initialScheduleDate) {
      setScheduleOn(true);
      // datetime-local input expects "YYYY-MM-DDTHH:MM"
      const d = new Date(initialScheduleDate + "T09:00");
      const pad = (n: number) => String(n).padStart(2, "0");
      setScheduleAt(
        `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T09:00`
      );
    }
  }, [initialScheduleDate]);
  // A scheduled post can also be given an end date: it goes up now and comes
  // down on the day the offer or announcement lapses.
  const [removeOn, setRemoveOn] = useState(false);
  const [removeAt, setRemoveAt] = useState("");

  // ── Per-format previews + saved crops ───────────────────────────
  const [crops, setCrops] = useState<Record<string, CropState>>({});
  /** destination+format currently being edited in the modal. `applyToIds`
   *  holds every selected branch when configuring several at once. */
  const [modalCtx, setModalCtx] = useState<{ targetId: string; method: PostMethod; applyToIds: string[] } | null>(null);
  /** draft crop being edited in the modal (committed on Save) */
  const [draftCrop, setDraftCrop] = useState<CropState>(DEFAULT_CROP);
  const [draftGalleryCategory, setDraftGalleryCategory] = useState<string>("EXTERIOR");
  /** formats that have been explicitly saved */
  const [configured, setConfigured] = useState<Set<string>>(new Set());
  /** Gallery category per destination+format (gallery only). */
  const [galleryCategories, setGalleryCategories] = useState<Record<string, string>>({});

  /** Per-destination chosen formats */
  const [formats, setFormats] = useState<Record<string, PostMethod[]>>({});

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  // Wizard navigation only — every input/handler stays mounted (steps are
  // shown with `hidden`), so no draft state or media preview is ever lost.
  const [postStep, setPostStep] = useState<1 | 2 | 3>(1);
  const { t: tr, locale } = useI18n();
  const pc: ComposerDict = tr.publish.composer;
  const methods = tr.publish.methods as MethodDict;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const methodLabel = (m: PostMethod) => methods[m].label;

  // ── Selection plumbing ──────────────────────────────────────────
  const applyAll = (v: boolean) => {
    setAllConnected(v);
    setSelected(v ? new Set(usableTargets.map((t) => t.id)) : new Set());
    if (v) usableTargets.forEach((t) => seedFormats(t, "default"));
  };

  const applyAllGoogle = (v: boolean) => {
    setAllGoogleConnected(v);
    if (v) {
      usableGoogleTargets.forEach((t) => selected.add(t.id));
    } else {
      usableGoogleTargets.forEach((t) => selected.delete(t.id));
    }
    setSelected(new Set(selected));
    if (v) usableGoogleTargets.forEach((t) => seedFormats(t, "default"));
  };

  const toggleTarget = (t: PublishTarget) => {
    const next = new Set(selected);
    const turningOn = !next.has(t.id);
    if (turningOn) next.add(t.id);
    else next.delete(t.id);
    setSelected(next);
    // Master switch only covers Meta social targets; Google has its own.
    const metaSelected = [...next].filter((id) => usableTargets.some((t) => t.id === id));
    setAllConnected(usableTargets.length > 0 && metaSelected.length === usableTargets.length);
    if (turningOn) seedFormats(t, "default");
  };

  const seedFormats = (t: PublishTarget, mode: "default" | "all") => {
    setFormats((prev) => {
      if (prev[t.id]?.length) return prev;
      const avail = methodsFor(t.platform, media?.type ?? null);
      // "all" means every FEED format - the avatar and promotion surfaces
      // are never seeded, only ever picked one by one.
      const chosen =
        mode === "default" ? avail.slice(0, 1) : avail.filter(isFeedMethod);
      return { ...prev, [t.id]: chosen };
    });
  };

  const availableFor = (t: PublishTarget) => methodsFor(t.platform, media?.type ?? null);
  const chosenFor = (t: PublishTarget) => {
    const avail = availableFor(t);
    return (formats[t.id] ?? []).filter((m) => avail.includes(m));
  };

  // Write the description from the caption + the selected branch/business.
  // The endpoint already grounds copy in the tenant's own Databank facts, so
  // it never invents prices or products; we only supply the context it needs.
  const writeDescriptionWithAI = async () => {
    if (!caption.trim()) {
      setDescNotice({ kind: "info", text: pc.aiDraftNeedTitle });
      return;
    }
    setDescDrafting(true);
    setDescNotice(null);
    try {
      const google = selectedTargets.filter((t) => t.platform === "google_reviews");
      const branch = google[0]?.name ?? selectedTargets[0]?.name ?? null;
      const r = await apiFetch("/api/v1/posts/ai-draft", {
        method: "POST",
        body: JSON.stringify({
          title: caption.trim(),
          post_type: "update",
          business_name: branch ?? undefined,
          location_name: google[0]?.name ?? undefined,
        }),
      });
      if (typeof r.description === "string" && r.description.trim()) {
        setDescription(r.description.trim());
        setDescNotice({ kind: "ok", text: pc.aiDraftDone });
      } else {
        setDescNotice({ kind: "err", text: pc.aiDraftFail });
      }
    } catch (e) {
      // Backend sends {"detail": "..."} — show the message, never raw JSON.
      let msg = pc.aiDraftFail;
      if (e instanceof Error) {
        try {
          const parsed = JSON.parse(e.message) as { detail?: unknown };
          if (typeof parsed.detail === "string" && parsed.detail.trim()) {
            msg = parsed.detail.slice(0, 200);
          }
        } catch { /* non-JSON error: keep the friendly fallback */ }
      }
      setDescNotice({ kind: "err", text: msg });
    } finally {
      setDescDrafting(false);
    }
  };

  const toggleFormat = (t: PublishTarget, m: PostMethod, applyTo?: PublishTarget[]) => {
    const targetsToApply = applyTo ?? [t];
    // Shared branches are the same platform and stay in sync, so one on/off
    // decision applies to every row instead of each row flipping on its own.
    const wasOn = chosenFor(targetsToApply[0]).includes(m);
    targetsToApply.forEach((target) => {
      const cur = chosenFor(target);
      const nextList = wasOn ? cur.filter((x) => x !== m) : [...cur, m];
      setFormats((prev) => ({ ...prev, [target.id]: nextList }));
      if (!wasOn) {
        // seed crop/defaults if not present
        const key = cropKeyFor(target.id, m);
        setCrops((prev) => (prev[key] ? prev : { ...prev, [key]: defaultCropFor(target.platform, m) }));
        if (m === "gallery") {
          setGalleryCategories((prev) => (prev[key] ? prev : { ...prev, [key]: "EXTERIOR" }));
        }
      }
    });
  };

  const toggleAllFormats = (t: PublishTarget, applyTo?: PublishTarget[]) => {
    const targetsToApply = applyTo ?? [t];
    // "All" covers feed formats only; avatar/promotion stay deliberate one-offs.
    const feed = availableFor(targetsToApply[0]).filter(isFeedMethod);
    const turningAll = chosenFor(targetsToApply[0]).filter(isFeedMethod).length < feed.length;
    targetsToApply.forEach((target) => {
      const nextList = turningAll
        ? [...chosenFor(target).filter((m) => !isFeedMethod(m)), ...feed]
        : chosenFor(target).filter((m) => !isFeedMethod(m));
      setFormats((prev) => ({ ...prev, [target.id]: nextList }));
      if (turningAll) {
        feed.forEach((m) => {
          const key = cropKeyFor(target.id, m);
          setCrops((prev) => (prev[key] ? prev : { ...prev, [key]: defaultCropFor(target.platform, m) }));
          if (m === "gallery") {
            setGalleryCategories((prev) => (prev[key] ? prev : { ...prev, [key]: "EXTERIOR" }));
          }
        });
      }
    });
  };

  // ── Media blob lifecycle ────────────────────────────────────────
  const pickMedia = (type: "image" | "video", url: string, fileName?: string, sizeBytes?: number, file?: File, width?: number, height?: number) => {
    if (blobRef.current && blobRef.current !== url) {
      URL.revokeObjectURL(blobRef.current);
    }
    if (url.startsWith("blob:")) blobRef.current = url;
    else blobRef.current = null;
    setMedia({ type, url, fileName, sizeBytes, width, height, file: file ?? null });
  };

  const clearMedia = () => {
    if (blobRef.current) URL.revokeObjectURL(blobRef.current);
    blobRef.current = null;
    setMedia(null);
  };

  useEffect(() => {
    return () => {
      if (blobRef.current) URL.revokeObjectURL(blobRef.current);
    };
  }, []);

  // ── Modal open/close ────────────────────────────────────────────
  const findTargetById = (id: string) =>
    targets.find((x) => x.id === id) ?? googleTargets.find((x) => x.id === id) ?? null;

  const openConfig = (t: PublishTarget, m: PostMethod, applyTo?: PublishTarget[]) => {
    const ids = (applyTo ?? [t]).map((x) => x.id);
    const key = cropKeyFor(t.id, m);
    setDraftCrop(crops[key] ?? defaultCropFor(t.platform, m));
    setDraftGalleryCategory(galleryCategories[key] ?? "EXTERIOR");
    setModalCtx({ targetId: t.id, method: m, applyToIds: ids });
  };

  const saveConfig = () => {
    if (!modalCtx) return;
    if (!findTargetById(modalCtx.targetId)) return;
    const ids = modalCtx.applyToIds.length ? modalCtx.applyToIds : [modalCtx.targetId];
    // One edit is written to every selected branch, so downstream publish
    // code still reads its normal per-destination keys.
    ids.forEach((id) => {
      const key = cropKeyFor(id, modalCtx.method);
      setCrops((prev) => ({ ...prev, [key]: draftCrop }));
      if (modalCtx.method === "gallery") {
        setGalleryCategories((prev) => ({ ...prev, [key]: draftGalleryCategory }));
      }
      setConfigured((prev) => new Set(prev).add(key));
    });
    setModalCtx(null);
  };

  const cancelConfig = () => {
    setModalCtx(null);
  };

  // ── Confirm ─────────────────────────────────────────────────────
  // Every destination in the confirm needs an id the backend can resolve and
  // at least one format. Google rows without a listing id cannot be targeted
  // at all (there is no location to post to), so they are dropped here rather
  // than enqueued into a job that can only fail.
  const confirmItems = selectedTargets
    .map((t) => ({ target: t, methods: chosenFor(t) }))
    .filter((i) => i.methods.length > 0 && externalAssetIdFor(i.target) !== null);
  const cf = tr.publish.confirm;
  const formatCount = confirmItems.reduce((n, i) => n + i.methods.length, 0);
  const destStr = confirmItems.length === 1 ? cf.destOne : fill(cf.destN, { n: fmt(confirmItems.length) });
  const fmtStr = formatCount === 1 ? cf.fmtOne : fill(cf.fmtN, { n: fmt(formatCount) });
  // A text-only post is valid for a Google update and Meta feed posts.
  // Everything else (and every Instagram post) needs an image.
  const needsMedia = confirmItems.some(({ target, methods }) =>
    methods.some(
      (m) =>
        MEDIA_ONLY_METHODS.has(m) ||
        (target.platform === "instagram" && m === "post"),
    ),
  );
  const canPublish = confirmItems.length > 0 && (media !== null || !needsMedia);
  const hasGoogle = confirmItems.some(({ target }) => target.platform === "google_reviews");
  // A Google post needs text or an image — the API refuses one with neither.
  const needsText = hasGoogle && confirmItems.some(({ methods }) =>
    methods.some((m) => m === "update" || m === "post"),
  );

  /** Every required field for the current draft, in step order. */
  const draftProblems = (): string[] => {
    const problems: string[] = [];
    if (confirmItems.length === 0) problems.push(pc.needDest);
    if (needsMedia && media === null) problems.push(pc.needMedia);
    if (needsText && media === null && !caption.trim() && !description.trim()) {
      problems.push(pc.captionRequired);
    }
    if (ctaType && ctaType !== "call" && !ctaUrl.trim()) problems.push(pc.ctaUrlRequired);
    const dateProblem = checkWindow({
      scheduleAt: scheduleOn ? scheduleAt : "",
      removeAt: removeOn ? removeAt : "",
      startDate: "",
      endDate: "",
    });
    if (dateProblem) problems.push(tr.publish.dates[dateProblem]);
    return problems;
  };

  /** Only the fields owned by the step the merchant is on. */
  const stepProblems = (step: 1 | 2 | 3): string[] => {
    if (step === 1) {
      const p: string[] = [];
      if (needsMedia && media === null) p.push(pc.needMedia);
      if (needsText && media === null && !caption.trim() && !description.trim()) {
        p.push(pc.captionRequired);
      }
      return p;
    }
    if (step === 2) {
      const p: string[] = [];
      if (ctaType && ctaType !== "call" && !ctaUrl.trim()) p.push(pc.ctaUrlRequired);
      return p;
    }
    return draftProblems();
  };

  const nextStep = () => {
    const problems = stepProblems(postStep);
    if (problems.length > 0) {
      setNotice(problems[0]);
      return;
    }
    setNotice(null);
    setPostStep((s) => Math.min(3, s + 1) as 1 | 2 | 3);
  };

  const openConfirm = () => {
    const problems = draftProblems();
    if (problems.length > 0) {
      setNotice(problems[0]);
      return;
    }
    if (media && media.type === "image" && media.width && media.height) {
      const googleSelected = confirmItems.some(({ target }) => target.platform === "google_reviews");
      if (googleSelected && (media.width < 250 || media.height < 250)) {
        setNotice("That image is below Google's 250×250px minimum. Pick a larger photo.");
        return;
      }
      if (googleSelected && media.sizeBytes && media.sizeBytes > 5 * 1024 * 1024) {
        setNotice("Google accepts photos up to 5MB. Pick a smaller file or compress it.");
        return;
      }
    }
    setNotice(null);
    setPublishError(null);
    setConfirmOpen(true);
  };

  const publishNow = async () => {
    // Text-only posts are valid for Google and Meta feeds, so a missing image
    // is not a reason to stop here: the API enforces which formats need one.
    if (publishing) return;
    setPublishing(true);
    setPublishError(null);
    try {
      // Dates are checked here, with the reason, so the tenant is not met by a
      // 422 from the API: a schedule must be set and in the future, and a
      // removal must come after the post goes out.
      if (scheduleOn && !scheduleAt) {
        throw new Error(tr.publish.dates.scheduleMissing);
      }
      if (removeOn && !removeAt) {
        throw new Error(pc.removeDateErr);
      }
      const dateProblem = checkWindow({
        scheduleAt: scheduleOn ? scheduleAt : "",
        removeAt: removeOn ? removeAt : "",
        startDate: "",
        endDate: "",
      });
      if (dateProblem) {
        throw new Error(tr.publish.dates[dateProblem]);
      }
      // Locally-picked files must go to our storage first: providers (and
      // the Google Business uploader) fetch the media from a public URL at
      // publish time, so a blob: URL can never be delivered. With no media
      // at all, the payload carries null and Google creates a text-only post.
      let mediaUrl: string | null = null;
      let mediaKey: string | null = null;
      let mediaType = "image";
      if (media) {
        mediaUrl = media.url;
        mediaKey = media.key ?? null;
        mediaType = media.type ?? "image";
        if (media.url.startsWith("blob:")) {
          if (!media.file) throw new Error(pc.fileGoneErr);
          const form = new FormData();
          form.append("file", media.file);
          const up = await apiFetch("/api/v1/media/upload", { method: "POST", body: form });
          mediaUrl = up.image_url;
          mediaKey = up.key ?? null;
          if (!mediaUrl) throw new Error(pc.uploadEmptyErr);
        }
      }

      // Gallery is published through the location-media API (photos added to
      // the GBP gallery with a chosen category). Everything else stays on the
      // unified publish jobs pipeline.
      const gallerySelections = confirmItems.flatMap(({ target, methods }) =>
        methods.includes("gallery")
          ? [
              {
                target,
                category:
                  galleryCategories[cropKeyFor(target.id, "gallery")] || "EXTERIOR",
                crop:
                  crops[cropKeyFor(target.id, "gallery")] ??
                  defaultCropFor(target.platform, "gallery"),
              },
            ]
          : []
      );

      // The crop editor is a CSS transform, so the file must be rasterised
      // before it is uploaded or the publisher ships the whole original.
      // One upload per distinct crop, reused by every format that shares it.
      const notices = new Set<string>();
      const cropUploads = new Map<string, { url: string | null; key: string | null }>();
      const mediaForCrop = async (crop: CropState) => {
        if (!media || crop.key === "orig") {
          return { url: mediaUrl, key: mediaKey };
        }
        if (mediaType === "video") {
          // A canvas cannot cut a video without dropping its audio track.
          notices.add(pc.cropVideoFallback);
          return { url: mediaUrl, key: mediaKey };
        }
        const sig = cropSignature(crop);
        const cached = cropUploads.get(sig);
        if (cached) return cached;

        let out = { url: mediaUrl, key: mediaKey };
        try {
          const file = await exportCroppedImage(
            { url: mediaUrl ?? media.url, file: media.file, type: mediaType },
            crop,
          );
          if (file) {
            const form = new FormData();
            form.append("file", file);
            const up = await apiFetch("/api/v1/media/upload", { method: "POST", body: form });
            if (!up.image_url) throw new Error(pc.uploadEmptyErr);
            out = { url: up.image_url, key: up.key ?? null };
          }
        } catch {
          // A pasted image on another origin can refuse to be read into a
          // canvas. Publishing the original beats failing the whole draft,
          // but the merchant is told the crop was not applied.
          notices.add(pc.cropFallback);
        }
        cropUploads.set(sig, out);
        return out;
      };

      // One idempotency key per draft, reused across retries: the backend
      // keys jobs as key:platform:asset:method, so a retry after a partial
      // failure must not queue a second copy of the same post.
      if (!publishAttemptRef.current) {
        publishAttemptRef.current = {
          key: crypto.randomUUID(),
          galleryDone: new Set<string>(),
        };
      }
      const attempt = publishAttemptRef.current;

      // Two things vary per request: the crop (each format bakes its own
      // file) and the destination. Grouping by crop is what lets one draft
      // publish a 1:1 avatar, a 16:9 promotion and an uncropped update
      // without shipping one file to all of them.
      type PostDestination = {
        platform: string;
        external_asset_id: string;
        methods: PostMethod[];
      };
      const groups = new Map<
        string,
        {
          destinations: PostDestination[];
          crop: CropState;
        }
      >();
      for (const item of confirmItems) {
        const methods = item.methods.filter((m) => m !== "gallery");
        if (methods.length === 0) continue;
        const assetId = externalAssetIdFor(item.target) as string;
        for (const method of methods) {
          const crop =
            crops[cropKeyFor(item.target.id, method)] ??
            defaultCropFor(item.target.platform, method);
          const groupKey = cropSignature(crop);
          let group = groups.get(groupKey);
          if (!group) {
            group = {
              destinations: [],
              crop,
            };
            groups.set(groupKey, group);
          }
          const existing = group.destinations.find(
            (d) => d.platform === item.target.platform && d.external_asset_id === assetId,
          );
          if (existing) existing.methods.push(method);
          else
            group.destinations.push({
              platform: item.target.platform,
              external_asset_id: assetId,
              methods: [method],
            });
        }
      }

      for (const [groupKey, group] of groups) {
        const variant = await mediaForCrop(group.crop);
        await apiFetch("/api/v1/channels/publish", {
          method: "POST",
          body: JSON.stringify({
            media_url: variant.url,
            media_key: variant.key,
            media_type: mediaType,
            caption,
            description,
            cta_type: ctaType || null,
            cta_url:
              ctaType && ctaType !== "call" ? ctaUrl.trim() || null : null,
            scheduled_at: scheduleOn && scheduleAt ? new Date(scheduleAt).toISOString() : null,
            delete_at: removeOn && removeAt ? new Date(removeAt).toISOString() : null,
            // Event and offer fields remain part of the publish API for posts
            // created elsewhere; the composer no longer sets them.
            start_date: null,
            end_date: null,
            event_title: null,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
            coupon_code: null,
            terms_conditions: null,
            // Google labels the post with the language the merchant wrote
            // it in, so an Arabic post is not published as English.
            language_code: GOOGLE_POST_LANGUAGE[locale] ?? "en-US",
            destinations: group.destinations,
            batch_id: attempt.key,
            idempotency_key: `${attempt.key}:${groupToken(groupKey)}`,
          }),
        });
      }

      // A gallery photo that fails must not roll back the posts that already
      // went out, and must not stop the other locations: each destination is
      // reported on its own.
      // A gallery photo can carry a crop too (a square product shot, say).
      const galleryCrops = new Map<string, File | null>();
      const croppedGalleryFile = async (crop: CropState): Promise<File | null> => {
        if (!media || crop.key === "orig" || mediaType === "video") return null;
        const sig = cropSignature(crop);
        if (galleryCrops.has(sig)) return galleryCrops.get(sig) ?? null;
        let file: File | null = null;
        try {
          file = await exportCroppedImage(
            { url: mediaUrl ?? media.url, file: media.file, type: mediaType },
            crop,
          );
        } catch {
          notices.add(pc.cropFallback);
        }
        galleryCrops.set(sig, file);
        return file;
      };

      const galleryErrors: string[] = [];
      const fallbacks: string[] = [];
      for (const g of gallerySelections) {
        if (!media && !mediaUrl) throw new Error(pc.needMedia);
        const channelId = g.target.id.startsWith("google:") ? g.target.id.slice(7) : g.target.id;
        // Already published on an earlier attempt of this same draft.
        if (attempt.galleryDone.has(channelId)) continue;
        const form = new FormData();
        form.append("category", g.category);
        if (caption) form.append("description", caption);
        const cropped = await croppedGalleryFile(g.crop);
        if (cropped) {
          form.append("file", cropped);
        } else if (media?.file) {
          form.append("file", media.file);
        } else if (media?.url && media.url.startsWith("blob:")) {
          throw new Error(pc.fileGoneErr);
        } else if (mediaUrl) {
          // Direct byte upload path: backend fetches and uploads bytes to Google.
          form.append("source_url", mediaUrl);
        } else {
          throw new Error(pc.needMedia);
        }
        try {
          const res = await apiFetch(`/api/v1/channels/${encodeURIComponent(channelId)}/google-media`, {
            method: "POST",
            body: form,
          });
          attempt.galleryDone.add(channelId);
          const fb = res?.categoryFallback;
          if (fb?.requested && fb.requested !== fb.used) {
            fallbacks.push(
              `${g.target.name}: Google does not allow the ${String(fb.requested).replace(/_/g, " ")} photo tag for this location — published as ${String(fb.used).replace(/_/g, " ")} instead.`,
            );
          }
        } catch (e) {
          galleryErrors.push(
            `${g.target.name}: ${e instanceof Error ? e.message : pc.publishFailed}`,
          );
        }
      }

      // A Promotion on Google is a cover photo. Confirm what actually happened
      // so the merchant is never left guessing whether it went to the gallery.
      const bannerPublished = confirmItems.some(
        ({ target, methods }) =>
          target.platform === "google_reviews" && methods.includes("banner"),
      );

      // Crop fallbacks and category fallbacks are both things the merchant
      // must hear about, so they share one banner.
      const allNotices = [...notices, ...fallbacks];
      if (bannerPublished) allNotices.push(pc.bannerSetNotice);
      if (galleryErrors.length) {
        // The draft stays open so the merchant can pick another category and
        // retry; the posts are not re-queued (same idempotency key).
        setPublishError(galleryErrors.join(" · "));
        setGalleryFallbacks(allNotices);
        return;
      }
      if (allNotices.length) {
        setGalleryFallbacks(allNotices);
        onNotice?.(allNotices.join(" "));
      }

      setConfirmOpen(false);
      clearMedia();
      setCaption("");
      setDescription("");
      setScheduleOn(false);
      setScheduleAt("");
      setRemoveOn(false);
      setRemoveAt("");
      setCtaType("");
      setCtaUrl("");
      setFormats({});
      setGalleryCategories({});
      // The draft is done: a new publish starts a new attempt.
      publishAttemptRef.current = null;
      onPublished?.();
    } catch (e) {
      setPublishError(e instanceof Error ? e.message : pc.publishFailed);
    } finally {
      setPublishing(false);
    }
  };

  // ── What's being edited (mirrors) ───────────────────────────────
  const activeTarget = modalCtx ? findTargetById(modalCtx.targetId) : null;
  // While modal is open, mirror the draft; otherwise last configured
  const mirrorTarget = modalCtx ? activeTarget : null;
  const mirrorMethod = modalCtx ? modalCtx.method : null;
  const mirrorCrop = modalCtx ? draftCrop : DEFAULT_CROP;

  // The persistent preview rail mirrors the first destination that actually
  // has a format chosen, so the frame reflects a real surface from step one —
  // not an empty placeholder that only fills in while a crop modal is open.
  const previewTarget = modalCtx
    ? activeTarget
    : (selectedTargets.find((t) => chosenFor(t).length > 0) ?? selectedTargets[0] ?? null);
  const previewMethod = modalCtx
    ? modalCtx.method
    : (previewTarget ? (chosenFor(previewTarget)[0] ?? "post") : "post");
  const previewCrop = modalCtx
    ? draftCrop
    : previewTarget
      ? (crops[cropKeyFor(previewTarget.id, previewMethod)] ?? defaultCropFor(previewTarget.platform, previewMethod))
      : DEFAULT_CROP;

  const thumb =
    media && mirrorTarget && mirrorMethod
      ? { cropKey: mirrorCrop.key, zoom: mirrorCrop.zoom, x: mirrorCrop.x, y: mirrorCrop.y }
      : null;
  const thumbLabel =
    media && mirrorTarget && mirrorMethod
      ? `${PLATFORM_META[mirrorTarget.platform].label} · ${methodLabel(mirrorMethod)}`
      : "";

  // ── Caption budget ──────────────────────────────────────────────
  const captionLimit =
    selectedTargets.length === 0
      ? PLATFORM_META.facebook.captionMax
      : Math.min(...selectedTargets.map((t) => PLATFORM_META[t.platform].captionMax));
  const captionOver = selectedTargets.filter((t) => caption.length > PLATFORM_META[t.platform].captionMax);
  const showCaptionWarn = caption.length > 0 && captionOver.length > 0;

  const openRow = (id: string) => {
    // In shared mode every branch uses one panel, so any chip scrolls there.
    if (postStep !== 2) setPostStep(2);
    const rowId = sharedMode ? selectedTargets[0].id : id;
    requestAnimationFrame(() => {
      document.getElementById(`dest-row-${rowId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  // The modal target + method
  const modalTarget = modalCtx ? findTargetById(modalCtx.targetId) : null;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="shrink-0 border-b border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-4 sm:px-6">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="mb-3 inline-flex items-center gap-1.5 rounded-[20px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-bold text-[var(--ui-ink-2)] transition duration-200 hover:bg-[var(--ui-sunken)] hover:text-[var(--ui-ink)] active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {pc.back}
          </button>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className={`text-[22px] font-bold tracking-[-0.02em] ${INK}`}>{pc.title}</h1>
            <p className={`mt-0.5 text-[13px] ${INK2}`}>
              {pc.sub}
            </p>
          </div>
        </div>
        {/* Step wizard — visual navigation only; all steps stay mounted. */}
        <ol className="mt-4 flex items-center gap-1 rounded-[24px] bg-[var(--ui-sunken)] p-1.5 sm:gap-2" aria-label="Post steps">
          {([
            { id: 1 as const, label: pc.wizard.step1 },
            { id: 2 as const, label: pc.wizard.step2 },
            { id: 3 as const, label: pc.wizard.step3 },
          ]).map((s, index) => {
            const active = postStep === s.id;
            const done = postStep > s.id;
            return (
              <li key={s.id} className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
                <button
                  type="button"
                  onClick={() => setPostStep(s.id)}
                  aria-current={active ? "step" : undefined}
                  className={`flex min-w-0 items-center gap-1.5 rounded-[20px] px-1 py-1 pr-1.5 transition duration-200 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] sm:gap-2 sm:px-1.5 sm:pr-2.5 ${
                    active
                      ? "bg-[var(--ui-surface)] text-[var(--ui-ink)] shadow-[0_8px_18px_-12px_rgba(61,29,110,0.55)]"
                      : done ? "text-[var(--ui-ink-2)]" : "text-[var(--ui-ink-2)] opacity-70"
                  }`}
                >
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[16px] text-[12px] font-bold transition ${
                    active
                      ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                      : done
                        ? "bg-[var(--ui-ink)]/10 text-[var(--ui-ink)]"
                        : "border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] text-[var(--ui-ink-2)]"
                  }`}>
                    {done ? "✓" : s.id}
                  </span>
                  <span className="hidden min-w-0 truncate text-[12px] font-semibold sm:inline sm:text-[13px]">{s.label}</span>
                </button>
                {index < 2 && <span className={`h-px min-w-[6px] flex-1 ${done ? "bg-[var(--ui-ink)]/40" : "bg-[var(--ui-line)]"}`} />}
              </li>
            );
          })}
        </ol>
        <p className={`mt-2 text-[11px] ${INK2}`}>
          {fill(pc.wizard.stepOf, { n: postStep })}
          <span className="ml-2 text-coral">* {pc.wizard.requiredHint}</span>
        </p>
      </header>

      {notice && (
        <div className="shrink-0 px-4 pt-3 sm:px-6">
          <div className="mx-auto max-w-[1280px]">
            <p role="alert" className="rounded-[20px] border border-red-500/40 bg-red-50 px-4 py-3 text-[13px] font-semibold text-red-700 shadow-[0_12px_28px_-22px_rgba(61,29,110,0.45)] dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-300">
              {notice}
            </p>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-[1280px] gap-5 px-4 pb-8 pt-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          {/* One working column. Steps use `hidden`, not unmounting: every
              input, ref and preview stays alive while navigating. */}
          <div className="min-w-0 space-y-5">
          {/* STEP 1 — media + message. */}
          <div className={postStep === 1 ? "space-y-5" : "hidden"}>
          <section aria-labelledby="publish-media-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-media-h" className={`text-[15px] font-bold ${INK}`}>
              {pc.stepMedia}
              {needsMedia && <span className="ml-1 text-coral" title={pc.wizard.requiredHint}>*</span>}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
              {pc.mediaSub}
            </p>
            <MediaSink
              media={media}
              onPick={pickMedia}
              onClear={clearMedia}
              thumb={thumb}
              thumbLabel={thumbLabel}
              platforms={confirmItems.map(({ target }) => target.platform)}
            />
            {needsMedia && media === null && (
              <p className="mt-3 text-[12px] font-semibold text-amber-700 dark:text-amber-400">
                An image or video is required for the selected destinations.
              </p>
            )}
          </section>

          <section aria-labelledby="ai-video-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
            <button
              type="button"
              id="ai-video-h"
              onClick={() => setAiOpen((v) => !v)}
              aria-expanded={aiOpen}
              className={`flex w-full items-center justify-between gap-2 text-left ${INK}`}
            >
              <span className="text-[14px] font-bold">{pc.aiTitle}</span>
              <span className={`text-[12px] font-semibold ${INK2}`}>{aiOpen ? "Hide" : "Show"}</span>
            </button>
            {aiOpen && (
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                {pc.aiSub}
              </p>
            )}
            <div className={aiOpen ? "" : "hidden"}>
              <AiVideoCreator googleTargets={googleTargets} />
            </div>
          </section>

          <section aria-labelledby="publish-message-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-message-h" className={`text-[15px] font-bold ${INK}`}>
              {pc.stepMessage}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
              {pc.messageSub}
            </p>
            <div className="space-y-3">
              <div>
                <div className="flex items-baseline justify-between">
                  <label htmlFor="pub-caption" className={`text-[12px] font-semibold ${INK2}`}>
                    {pc.caption}
                    {needsText && !media && <span className="ml-1 text-coral" title={pc.wizard.requiredHint}>*</span>}
                  </label>
                  <span
                    className={`text-[11px] ${
                      caption.length > captionLimit ? "font-semibold text-amber-600 dark:text-amber-400" : INK2
                    }`}
                  >
                    {fmt(caption.length)} / {fmt(captionLimit)}
                  </span>
                </div>
                <textarea
                  id="pub-caption"
                  value={caption}
                  onChange={(e) => setCaption(e.target.value)}
                  rows={2}
                  maxLength={PLATFORM_META.facebook.captionMax}
                  placeholder={pc.captionPh}
                  className={`${FIELD} mt-1 w-full resize-y`}
                />
                {showCaptionWarn && (
                  <p
                    role="status"
                    className="mt-1.5 rounded-[16px] border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-[12px] font-medium text-amber-700 dark:text-amber-400"
                  >
                    {fill(pc.truncates, { names: captionOver.map((t) => fill(pc.truncName, { name: PLATFORM_META[t.platform].label, max: fmt(PLATFORM_META[t.platform].captionMax) })).join(" · ") })}
                  </p>
                )}
              </div>
              <div>
                <div className="flex items-baseline justify-between gap-2">
                  <label htmlFor="pub-description" className={`text-[12px] font-semibold ${INK2}`}>
                    {pc.description}
                  </label>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={writeDescriptionWithAI}
                      disabled={descDrafting}
                      title={pc.aiWriteDescHint}
                      className="inline-flex items-center gap-1 rounded-[20px] border border-deep-violet/25 bg-deep-violet/[0.06] px-2.5 py-1 text-[11px] font-bold text-deep-violet outline-none transition hover:bg-deep-violet/[0.12] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] disabled:opacity-50 dark:border-fog/15 dark:text-fog dark:hover:bg-fog/[0.08]"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5" aria-hidden>
                        <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3z" strokeLinejoin="round" />
                        <path d="M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15z" strokeLinejoin="round" />
                      </svg>
                      {descDrafting ? pc.aiDrafting : pc.aiWriteDesc}
                    </button>
                    <span className={`text-[11px] ${INK2}`}>{fmt(description.length)}</span>
                  </div>
                </div>
                <textarea
                  id="pub-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={4}
                  maxLength={PLATFORM_META.facebook.captionMax}
                  placeholder={pc.descPh}
                  className={`${FIELD} mt-1 w-full resize-y`}
                />
                {descNotice && (
                  <p
                    role="status"
                    className={`mt-1.5 rounded-[16px] border px-3 py-2 text-[12px] font-medium ${
                      descNotice.kind === "err"
                        ? "border-coral/40 bg-coral/10 text-coral"
                        : descNotice.kind === "ok"
                          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                          : "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                    }`}
                  >
                    {descNotice.text}
                  </p>
                )}
              </div>
            </div>
          </section>

          </div>{/* end step 1 */}

          {/* STEP 3 — schedule. The live preview lives in the persistent rail. */}
          <div className={postStep === 3 ? "space-y-5" : "hidden"}>
          <section aria-labelledby="publish-schedule-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-schedule-h" className={`text-[15px] font-bold ${INK}`}>
              {pc.stepWhen}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>{pc.whenSub}</p>
            <div className="flex flex-wrap items-center gap-3">
              <ScheduleToggle scheduleOn={scheduleOn} setScheduleOn={setScheduleOn} label={pc.scheduleLater} />
              {scheduleOn && (
                <input
                  type="datetime-local"
                  value={scheduleAt}
                  onChange={(e) => setScheduleAt(e.target.value)}
                  aria-label={pc.publishAt}
                  min={minLocalInput()}
                  className={`${FIELD} w-full sm:w-64`}
                />
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-[var(--ui-line)] pt-3">
              <ScheduleToggle scheduleOn={removeOn} setScheduleOn={setRemoveOn} label={pc.removeLater} />
              {removeOn && (
                <input
                  type="datetime-local"
                  value={removeAt}
                  onChange={(e) => setRemoveAt(e.target.value)}
                  aria-label={pc.removeAtAria}
                  min={minLocalInput()}
                  className={`${FIELD} w-full sm:w-64`}
                />
              )}
            </div>
            {removeOn && (
              <p className={`mt-2 text-[11px] ${INK2}`}>
                {pc.removeNote}
              </p>
            )}
          </section>

          </div>{/* end step 3 */}

          {/* STEP 2 — destinations + their per-platform configuration */}
          <div className={postStep === 2 ? "space-y-5" : "hidden"}>
          <div className="space-y-5">
          <section aria-labelledby="publish-cta-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-cta-h" className={`text-[15px] font-bold ${INK}`}>
              {pc.wizard.ctaTitle}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
              {pc.ctaHint}
            </p>
            <div>
              <label htmlFor="pub-cta-type" className={`text-[12px] font-semibold ${INK2}`}>
                {pc.ctaType}
              </label>
              <select
                id="pub-cta-type"
                value={ctaType}
                onChange={(e) => {
                  setCtaType(e.target.value);
                  if (e.target.value === "call") setCtaUrl("");
                }}
                className={`${FIELD} mt-1 w-full`}
              >
                <option value="">{pc.ctaTypePh}</option>
                {CTA_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {pc.ctaTypes[value]}
                  </option>
                ))}
              </select>
              {ctaType && ctaType !== "call" && (
                <input
                  type="url"
                  value={ctaUrl}
                  onChange={(e) => setCtaUrl(e.target.value)}
                  placeholder={pc.ctaUrlPh}
                  aria-label={pc.ctaUrlPh}
                  className={`${FIELD} mt-1.5 w-full`}
                />
              )}
            </div>
          </section>
          <section aria-labelledby="publish-dest-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-dest-h" className={`text-[15px] font-bold ${INK}`}>
              {pc.stepDest}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
              {pc.destSub}
            </p>
            <DestinationSelector
              targets={targets}
              status={targetsStatus}
              allConnected={allConnected}
              googleTargets={usableGoogleTargets}
              allGoogleConnected={allGoogleConnected}
              selected={selected}
              onSelectAll={applyAll}
              onApplyAllGoogle={applyAllGoogle}
              onToggleTarget={toggleTarget}
              onToggleGoogleTarget={toggleTarget}
            />
            {selectedTargets.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[var(--ui-line)] pt-3">
                {selectedTargets.map((target) => {
                  const hasFormat = chosenFor(target).length > 0;
                  return (
                    <button
                      key={target.id}
                      type="button"
                      onClick={() => openRow(target.id)}
                      title={hasFormat ? fill(pc.reviewRow, { name: target.name }) : fill(pc.noFormatRow, { name: target.name })}
                      className={`inline-flex max-w-full items-center gap-1.5 rounded-[20px] border px-2.5 py-1.5 text-[11px] font-bold transition duration-200 hover:bg-[var(--ui-sunken)] active:scale-[0.97] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                        hasFormat
                          ? "border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink)]"
                          : "border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                      }`}
                    >
                      <PlatformMark platform={target.platform} size={12} />
                      <span className="max-w-[140px] truncate">{target.name}</span>
                      <span className="font-medium opacity-70">
                        {hasFormat ? chosenFor(target)[0] ? methodLabel(chosenFor(target)[0]) : "" : pc.noFormat}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
          </div>{/* destinations column */}

          {/* Configure formats — roomy, grouped cards per destination */}
          {selectedTargets.length > 0 && (
            <section aria-labelledby="publish-formats-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 id="publish-formats-h" className={`text-[15px] font-bold ${INK}`}>
                    {pc.formatsTitle}
                  </h2>
                  <p className={`mt-0.5 text-[12px] ${INK2}`}>
                    {pc.formatsSub}
                  </p>
                </div>
                <span className="rounded-[20px] bg-[var(--ui-sunken)] px-3 py-1 text-[11px] font-bold text-[var(--ui-ink)]">
                  {fmt(formatCount)} selected
                </span>
              </div>
              {selectedTargets.some((t) =>
                availableFor(t).some((m) => m === "profile" || m === "banner" || m === "gallery"),
              ) && (
                <div className="mt-3 flex items-start gap-2.5 rounded-[20px] border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5">
                  <svg className="mt-0.5 h-4 w-4 shrink-0 text-amber-700 dark:text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 11v5" strokeLinecap="round" />
                    <path d="M12 8h.01" strokeLinecap="round" />
                  </svg>
                  <p className="text-[11.5px] leading-relaxed text-amber-800 dark:text-amber-300">
                    {pc.formatsNote} Gallery photos are added to the location&apos;s photo gallery — pick a category when you configure it.
                  </p>
                </div>
              )}
              {sharedMode && (
                <div className="mt-3 flex items-center gap-2 rounded-[20px] border border-emerald-500/30 bg-emerald-500/[0.07] px-3.5 py-2.5 text-[11.5px] font-semibold text-emerald-700 dark:text-emerald-400">
                  <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" strokeLinecap="round" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" strokeLinecap="round" />
                  </svg>
                  One setup for all {fmt(selectedTargets.length)} locations. Pick a format and configure it once — it applies everywhere.
                </div>
              )}
              <div className="mt-4 space-y-4">
                {(sharedMode ? selectedTargets.slice(0, 1) : selectedTargets).map((t) => {
                  const applyTargets = sharedMode ? selectedTargets : [t];
                  const avail = availableFor(t);
                  // Shared mode shows a format as on only when every selected
                  // location has it, so the one panel never lies about the set.
                  const chosen = sharedMode
                    ? avail.filter((m) => selectedTargets.every((x) => chosenFor(x).includes(m)))
                    : chosenFor(t);
                  const postFormats = avail.filter((m) => m !== "gallery" && m !== "profile" && m !== "banner");
                  const surfaceFormats = avail.filter((m) => m === "gallery" || m === "profile" || m === "banner");
                  const renderFormat = (m: PostMethod) => {
                    const isOn = chosen.includes(m);
                    const key = cropKeyFor(t.id, m);
                    const isConfigured = configured.has(key);
                    const crop = crops[key] ?? defaultCropFor(t.platform, m);
                    return (
                      <button
                        key={m}
                        type="button"
                        onClick={() => {
                          // One click updates every selected location in
                          // shared mode; unselected also opens the editor.
                          toggleFormat(t, m, applyTargets);
                          if (isOn) {
                            if (
                              modalCtx?.method === m &&
                              applyTargets.some((x) => modalCtx.applyToIds.includes(x.id))
                            ) {
                              cancelConfig();
                            }
                          } else {
                            openConfig(t, m, applyTargets);
                          }
                        }}
                        aria-pressed={isOn}
                        className={`flex items-center gap-3 rounded-[20px] border p-2.5 text-left transition duration-200 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                          isOn
                            ? "border-emerald-500/70 bg-[var(--ui-surface)] shadow-[0_12px_26px_-16px_rgba(16,185,129,0.85)]"
                            : "border-[var(--ui-line)] bg-[var(--ui-sunken)] hover:border-[var(--ui-ink)]/30 hover:bg-[var(--ui-surface)]"
                        }`}
                      >
                        <FormatThumb media={media} crop={crop} size={40} className="rounded-[12px]" />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className={`truncate text-[12px] font-bold ${INK}`}>{methodLabel(m)}</span>
                            {isOn && isConfigured && (
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" title="Crop set" />
                            )}
                          </span>
                          <span className={`mt-0.5 block text-[10.5px] leading-snug line-clamp-2 ${INK2}`}>
                            {METHOD_META[m].hint}
                          </span>
                        </span>
                        <span
                          aria-hidden={!isOn}
                          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 transition ${
                            isOn
                              ? "border-emerald-500 bg-white text-emerald-600 shadow-[0_6px_14px_-8px_rgba(16,185,129,0.9)] dark:bg-fog/10 dark:text-emerald-400"
                              : "border-[var(--ui-line-strong)] bg-[var(--ui-surface)]"
                          }`}
                        >
                          {isOn && (
                            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" aria-hidden>
                              <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </span>
                      </button>
                    );
                  };
                  return (
                    <div key={t.id} id={`dest-row-${t.id}`} className="overflow-hidden rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-sunken)]">
                      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ui-line)] px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-[var(--ui-surface)] shadow-[0_8px_18px_-12px_rgba(61,29,110,0.6)]">
                            <PlatformMark platform={t.platform} size={16} />
                          </span>
                          <div className="min-w-0">
                            <p className={`truncate text-[13px] font-bold ${INK}`}>
                              {sharedMode ? `All ${fmt(selectedTargets.length)} locations` : t.name}
                            </p>
                            <p className={`text-[11px] ${INK2}`}>
                              {sharedMode
                                ? "Same formats and settings on every location"
                                : `${fmt(chosen.length)} of ${fmt(avail.length)} selected`}
                            </p>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => toggleAllFormats(t, applyTargets)}
                          title={pc.allTitle}
                          className="rounded-[20px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3.5 py-1.5 text-[11px] font-bold text-[var(--ui-ink-2)] transition duration-200 hover:bg-[var(--ui-sunken)] active:scale-[0.97] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                        >
                          {pc.allPill}
                        </button>
                      </div>
                      <div className="p-3 sm:p-4">
                        {postFormats.length > 0 && (
                          <>
                            <p className={`mb-2 text-[10px] font-bold uppercase tracking-[0.12em] ${INK2}`}>Posts</p>
                            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{postFormats.map(renderFormat)}</div>
                          </>
                        )}
                        {surfaceFormats.length > 0 && (
                          <>
                            <p className={`mb-2 mt-4 text-[10px] font-bold uppercase tracking-[0.12em] ${INK2}`}>Location media</p>
                            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{surfaceFormats.map(renderFormat)}</div>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          </div>{/* end step 2 */}

          {/* Step-local footer: navigation belongs to the step, and the
              publish action only exists on the final step. */}
          <div className="rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)] sm:p-5">
            {postStep === 3 && galleryFallbacks.length > 0 && (
              <div className="mb-3 space-y-1" role="status">
                {galleryFallbacks.map((f) => (
                  <p key={f} className="text-[12px] font-medium text-amber-700 dark:text-amber-400">
                    {f}
                  </p>
                ))}
              </div>
            )}
            {stepProblems(postStep).length > 0 && (
              <div className="mb-3 space-y-1 rounded-[20px] border border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5" role="status">
                {stepProblems(postStep).map((problem) => (
                  <p key={problem} className="text-[12px] font-semibold text-amber-800 dark:text-amber-300">
                    {problem}
                  </p>
                ))}
              </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                {postStep > 1 && (
                  <button
                    type="button"
                    onClick={() => setPostStep((s) => Math.max(1, s - 1) as 1 | 2 | 3)}
                    className="clay-btn-secondary px-5 py-2.5 text-[13px] font-bold text-[var(--ui-ink)] transition duration-200 hover:bg-[var(--ui-sunken)] active:translate-y-0.5 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                  >
                    {pc.wizard.back}
                  </button>
                )}
                {postStep < 3 && (
                  <p className={`text-[12px] font-medium ${INK2}`}>
                    {fill(pc.wizard.stepOf, { n: postStep })}
                  </p>
                )}
              </div>
              {postStep < 3 ? (
                <button
                  type="button"
                  onClick={nextStep}
                  className="clay-btn-primary px-6 py-2.5 text-[13px] font-bold text-[var(--ui-on-ink)] transition duration-200 hover:opacity-90 active:translate-y-0.5 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                >
                  {pc.wizard.next}
                </button>
              ) : (
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <p className={`max-w-[340px] text-[12px] font-medium ${INK2}`} role="status" aria-live="polite">
                    {confirmItems.length === 0
                      ? pc.readyNone
                      : `${pc.readyPre}${destStr} · ${fmtStr}`}
                    {scheduleOn && scheduleAt
                      ? fill(pc.scheduledOn, { date: new Date(scheduleAt).toLocaleString(dateLocale, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) })
                      : ""}
                  </p>
                  <button
                    type="button"
                    onClick={openConfirm}
                    disabled={!canPublish}
                    title={!canPublish ? (confirmItems.length === 0 ? "Select at least one destination." : needsMedia ? "Add an image or video first." : undefined) : undefined}
                    className="clay-btn-primary px-6 py-2.5 text-[13px] font-bold text-[var(--ui-on-ink)] transition duration-200 hover:opacity-90 active:translate-y-0.5 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                  >
                    {scheduleOn ? pc.reviewSchedule : pc.reviewPublish}
                  </button>
                </div>
              )}
            </div>
          </div>
          </div>{/* end working column */}

          {/* Persistent preview rail — visible on every step, so the frame
              always mirrors the destination/format it will actually use. */}
          <aside className="order-first min-w-0 lg:order-none lg:sticky lg:top-4 lg:self-start">
            <section aria-labelledby="publish-preview-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="publish-preview-h" className={`text-[15px] font-bold ${INK}`}>
                  {pc.stepPreview}
                </h2>
                <p className={`text-[12px] ${INK2}`} role="status">
                  {previewTarget && previewMethod
                    ? fill(pc.mirroring, { name: previewTarget.name, method: methodLabel(previewMethod) })
                    : (
                      <>
                        <span className="lg:hidden">{pc.mirrorNoneWide}</span>
                        <span className="hidden lg:inline">{pc.mirrorNoneSide}</span>
                      </>
                    )}
                </p>
              </div>
              <div className="mt-4">
                <DestinationPreview
                  target={previewTarget}
                  method={previewMethod}
                  media={media ?? { type: null, url: "" }}
                  caption={caption}
                  description={description}
                  crop={previewCrop}
                />
              </div>
            </section>
          </aside>
        </div>
      </div>


      {/* Configuration modal — opens when a format pill is clicked */}
      {modalCtx && modalTarget && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={fill(pc.modalAria, { name: modalTarget.name, method: methodLabel(modalCtx.method) })}
          onClick={(e) => {
            if (e.target === e.currentTarget) cancelConfig();
          }}
          className="fixed inset-0 z-50 bg-[rgba(0,0,0,0.45)] sm:flex sm:items-center sm:justify-center sm:p-4"
        >
          <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-[var(--ui-surface)] sm:h-auto sm:max-h-[90dvh] sm:max-w-5xl sm:rounded-[32px] sm:border sm:border-[var(--ui-line)] sm:shadow-2xl">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--ui-line)] p-4 sm:border-0 sm:p-5 sm:pb-0">
              <div>
                <h2 className="text-[15px] font-bold text-[var(--ui-ink)] sm:text-[16px]">
                  {fill(pc.modalTitle, { name: modalTarget.name, method: methodLabel(modalCtx.method) })}
                </h2>
                <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                  {modalCtx.applyToIds.length > 1
                    ? `This setup applies to ${fmt(modalCtx.applyToIds.length)} selected locations.`
                    : pc.modalSub}
                </p>
              </div>
              <button
                type="button"
                onClick={cancelConfig}
                aria-label={pc.close}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-bold text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
              >
                ×
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5 sm:pt-4">
              <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-start sm:justify-center sm:gap-8">
                <div className="shrink-0">
                  <DestinationPreview
                    target={modalTarget}
                    method={modalCtx.method}
                    media={media ?? { type: null, url: "" }}
                    caption={caption}
                    description={description}
                    crop={draftCrop}
                  />
                </div>
                <div className="w-full max-w-[320px] shrink-0 space-y-3">
                  {modalCtx.method === "gallery" && (
                    <div>
                      <label className="mb-1 block text-[12px] font-semibold text-[var(--ui-ink)]">Gallery category</label>
                      <select
                        value={draftGalleryCategory}
                        onChange={(e) => setDraftGalleryCategory(e.target.value)}
                        className="w-full clay-input px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus:border-deep-violet/40"
                      >
                        {GALLERY_CATEGORIES.map((c) => (
                          <option key={c} value={c}>{c.replace(/_/g, " ")}</option>
                        ))}
                      </select>
                      <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">Choose where this photo appears in the location gallery on Google.</p>
                    </div>
                  )}
                  <CropFrame
                    key={`${modalCtx.targetId}-${modalCtx.method}`}
                    url={media?.url ?? null}
                    type={media?.type ?? null}
                    cropKey={draftCrop.key}
                    zoom={draftCrop.zoom}
                    offset={{ x: draftCrop.x, y: draftCrop.y }}
                    onCropKey={(k) => setDraftCrop((prev) => ({ ...prev, key: k, zoom: 1, x: 0, y: 0 }))}
                    onZoom={(z) => setDraftCrop((prev) => ({ ...prev, zoom: z }))}
                    onOffset={(o) => setDraftCrop((prev) => ({ ...prev, x: o.x, y: o.y }))}
                  />
                </div>
              </div>
            </div>

            <div className="flex shrink-0 flex-col-reverse gap-2 border-t border-[var(--ui-line)] p-4 sm:flex-row sm:justify-end sm:border-0 sm:p-5 sm:pt-0">
              <button
                type="button"
                onClick={cancelConfig}
                className="clay-input px-4 py-2.5 text-[13px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] sm:py-2"
              >
                {pc.cancel}
              </button>
              <button
                type="button"
                onClick={saveConfig}
                className="clay-btn-primary px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] sm:py-2"
              >
                {fill(pc.saveMethod, { method: methodLabel(modalCtx.method) })}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirmOpen}
        items={confirmItems}
        media={media ?? { type: null, url: "" }}
        captionLen={caption.trim().length}
        descriptionLen={description.trim().length}
        scheduled={scheduleOn && scheduleAt ? scheduleAt : null}
        removes={removeOn && removeAt ? removeAt : null}
        busy={publishing}
        error={publishError}
        onConfirm={publishNow}
        onClose={() => setConfirmOpen(false)}
      />
    </div>
  );
}

/* ── Inline sub-pieces ───────────────────────────────────────────── */

function ScheduleToggle({
  scheduleOn,
  setScheduleOn,
  label,
}: {
  scheduleOn: boolean;
  setScheduleOn: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={scheduleOn}
      onClick={() => setScheduleOn(!scheduleOn)}
      className="flex items-center gap-3"
    >
      <span
        className={`relative inline-block h-6 w-10 shrink-0 rounded-full ${
          scheduleOn ? "bg-[var(--ui-ink)]" : "border border-[var(--ui-line-strong)] bg-[var(--ui-sunken)]"
        }`}
      >
        <span
          className={`absolute left-0 top-0.5 h-5 w-5 rounded-full transition-transform ${
            scheduleOn
              ? "translate-x-[18px] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
              : "translate-x-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
          }`}
        />
      </span>
      <span className={`text-[13px] font-semibold ${INK}`}>{label}</span>
    </button>
  );
}
