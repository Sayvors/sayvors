"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { INK, INK2 } from "@/components/channels/instagram/ui";
import { apiFetch } from "@/lib/api-rag";
import { externalAssetIdFor } from "@/lib/publish-targets";
import { checkWindow, minLocalInput } from "@/lib/publish-schedule";
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

type MethodDict = Dict["publish"]["methods"];
type ComposerDict = Dict["publish"]["composer"];

/** Formats that cannot be published without an image. Google's What's New /
 * Event / Offer and Meta feed posts allow a text-only post. Gallery,
 * profile and banner are image surfaces. */
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
 * Destinations are picked in the aside (step 3) with an "all connected"
 * master switch. Each selected destination shows method pills (Feed post /
 * Story / Reel / Status) right below it — clicking a pill opens a wide
 * modal where that specific platform+method gets its own preview + crop
 * editor + Save button. Crop state is keyed per destination+method so every
 * format keeps its own framing, and the step-1 thumbnail + live preview
 * mirror whatever you're currently configuring.
 *
 * Confirming uploads locally-picked media to /api/v1/media/upload (the
 * provider must fetch the files from a public URL at publish time), then
 * creates one job per destination+format via POST /api/v1/channels/publish.
 * A locally-picked file that never uploads means the post never leaves,
 * so only https URLs and stored files make it through the confirm gate.
 */

const FIELD =
  "rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]";

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
          className="w-full rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
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
            className="mt-2 w-full rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
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
              className="h-9 w-full cursor-pointer rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)]" />
          </div>
          <div>
            <span className={`block text-[10px] ${INK2} mb-1`}>{pc.aiAccent}</span>
            <input type="color" value={accent} onChange={(e) => setAccent(e.target.value)}
              className="h-9 w-full cursor-pointer rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)]" />
          </div>
          <div>
            <span className={`block text-[10px] ${INK2} mb-1`}>{pc.aiBg}</span>
            <input type="color" value={bg} onChange={(e) => setBg(e.target.value)}
              className="h-9 w-full cursor-pointer rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)]" />
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
      <div className={`rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-2 text-[11px] ${INK2}`}>
        {fill(pc.aiFile, { name: fileName })}
        <span className="ml-1 opacity-60">{fill(pc.aiFileSaved, { name: fileName })}</span>
      </div>

      {/* actions */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={generate}
          className="w-full rounded-[10px] bg-[var(--ui-ink)] px-3 py-2 text-[12px] font-bold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        >
          {pc.aiCreate}
        </button>
      </div>

      {/* video player / preview */}
      <div className="overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)]">
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
        className="w-full rounded-[10px] border border-dashed border-[var(--ui-line-strong)] bg-[var(--ui-sunken)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink-2)] opacity-60 cursor-not-allowed"
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
  // A promotional post has an end date: it goes up now and comes down
  // on the day the offer lapses.
  const [removeOn, setRemoveOn] = useState(false);
  const [removeAt, setRemoveAt] = useState("");

  // Event/offer window. Google requires an `event` object for EVENT and
  // OFFER topics, so the composer collects the schedule here; when left
  // blank the publisher defaults it (now → +7 days).
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // ── Per-format previews + saved crops ───────────────────────────
  const [crops, setCrops] = useState<Record<string, CropState>>({});
  /** destination+format currently being edited in the modal */
  const [modalCtx, setModalCtx] = useState<{ targetId: string; method: PostMethod } | null>(null);
  /** draft crop being edited in the modal (committed on Save) */
  const [draftCrop, setDraftCrop] = useState<CropState>(DEFAULT_CROP);
  const [draftGalleryCategory, setDraftGalleryCategory] = useState<string>("EXTERIOR");
  /** Coupon code + terms of a Promotion (offer) post, per destination. */
  const [offerDetails, setOfferDetails] = useState<
    Record<string, { coupon: string; terms: string }>
  >({});
  const [draftCoupon, setDraftCoupon] = useState("");
  const [draftTerms, setDraftTerms] = useState("");
  /** formats that have been explicitly saved */
  const [configured, setConfigured] = useState<Set<string>>(new Set());
  /** Gallery category per destination+format (gallery only). */
  const [galleryCategories, setGalleryCategories] = useState<Record<string, string>>({});

  /** Per-destination chosen formats */
  const [formats, setFormats] = useState<Record<string, PostMethod[]>>({});

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
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
      // "all" means every FEED format — the avatar and cover surfaces
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

  const toggleFormat = (t: PublishTarget, m: PostMethod) => {
    const cur = chosenFor(t);
    const wasOn = cur.includes(m);
    const nextList = wasOn ? cur.filter((x) => x !== m) : [...cur, m];
    setFormats((prev) => ({ ...prev, [t.id]: nextList }));
    if (!wasOn) {
      // seed crop/defaults if not present
      const key = cropKeyFor(t.id, m);
      setCrops((prev) => (prev[key] ? prev : { ...prev, [key]: defaultCropFor(t.platform, m) }));
      if (m === "gallery") {
        setGalleryCategories((prev) => (prev[key] ? prev : { ...prev, [key]: "EXTERIOR" }));
      }
    }
  };

  const toggleAllFormats = (t: PublishTarget) => {
    // "All" covers the feed formats only. Selecting every pill would
    // also replace the account's avatar and cover image, which must
    // stay a deliberate, one-at-a-time choice.
    const feed = availableFor(t).filter(isFeedMethod);
    const cur = chosenFor(t);
    const turningAll = cur.filter(isFeedMethod).length < feed.length;
    const nextList = turningAll
      ? [...cur.filter((m) => !isFeedMethod(m)), ...feed]
      : cur.filter((m) => !isFeedMethod(m));
    setFormats((prev) => ({ ...prev, [t.id]: nextList }));
    if (turningAll) {
      feed.forEach((m) => {
        const key = cropKeyFor(t.id, m);
        setCrops((prev) => (prev[key] ? prev : { ...prev, [key]: defaultCropFor(t.platform, m) }));
        if (m === "gallery") {
          setGalleryCategories((prev) => (prev[key] ? prev : { ...prev, [key]: "EXTERIOR" }));
        }
      });
    }
  };

  // ── Media blob lifecycle ────────────────────────────────────────
  const pickMedia = (type: "image" | "video", url: string, fileName?: string, sizeBytes?: number, file?: File) => {
    if (blobRef.current && blobRef.current !== url) {
      URL.revokeObjectURL(blobRef.current);
    }
    if (url.startsWith("blob:")) blobRef.current = url;
    else blobRef.current = null;
    setMedia({ type, url, fileName, sizeBytes, file: file ?? null });
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

  const openConfig = (t: PublishTarget, m: PostMethod) => {
    const key = cropKeyFor(t.id, m);
    setDraftCrop(crops[key] ?? defaultCropFor(t.platform, m));
    setDraftGalleryCategory(galleryCategories[key] ?? "EXTERIOR");
    setDraftCoupon(offerDetails[key]?.coupon ?? "");
    setDraftTerms(offerDetails[key]?.terms ?? "");
    setModalCtx({ targetId: t.id, method: m });
  };

  const saveConfig = () => {
    if (!modalCtx) return;
    const t = findTargetById(modalCtx.targetId);
    if (!t) return;
    const key = cropKeyFor(modalCtx.targetId, modalCtx.method);
    setCrops((prev) => ({ ...prev, [key]: draftCrop }));
    if (modalCtx.method === "gallery") {
      setGalleryCategories((prev) => ({ ...prev, [key]: draftGalleryCategory }));
    }
    if (modalCtx.method === "offer") {
      setOfferDetails((prev) => ({
        ...prev,
        [key]: { coupon: draftCoupon.trim(), terms: draftTerms.trim() },
      }));
    }
    setConfigured((prev) => new Set(prev).add(key));
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
  // Google requires an event window for EVENT and OFFER topics, so the
  // composer only asks for the dates when one of those is actually chosen.
  const needsEventWindow = confirmItems.some(({ methods }) =>
    methods.some((m) => m === "event" || m === "offer"),
  );
  const cf = tr.publish.confirm;
  const formatCount = confirmItems.reduce((n, i) => n + i.methods.length, 0);
  const destStr = confirmItems.length === 1 ? cf.destOne : fill(cf.destN, { n: fmt(confirmItems.length) });
  const fmtStr = formatCount === 1 ? cf.fmtOne : fill(cf.fmtN, { n: fmt(formatCount) });
  // A text-only post is valid for Google What's New / Event / Offer and Meta
  // feed posts. Everything else (and every Instagram post) needs an image.
  const needsMedia = confirmItems.some(({ target, methods }) =>
    methods.some(
      (m) =>
        MEDIA_ONLY_METHODS.has(m) ||
        (target.platform === "instagram" && m === "post"),
    ),
  );
  const canPublish = confirmItems.length > 0 && (media !== null || !needsMedia);

  const openConfirm = () => {
    if (needsMedia && media === null) {
      setNotice(pc.needMedia);
      return;
    }
    if (confirmItems.length === 0) {
      setNotice(pc.needDest);
      return;
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
      // 422 from the API: a schedule must be set and in the future, a removal
      // must come after the post goes out, and an event must end after it starts.
      if (scheduleOn && !scheduleAt) {
        throw new Error(tr.publish.dates.scheduleMissing);
      }
      if (removeOn && !removeAt) {
        throw new Error(pc.removeDateErr);
      }
      const dateProblem = checkWindow({
        scheduleAt: scheduleOn ? scheduleAt : "",
        removeAt: removeOn ? removeAt : "",
        startDate: needsEventWindow ? startDate : "",
        endDate: needsEventWindow ? endDate : "",
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
      const postDestinations = confirmItems
        .map(({ target: t, methods }) => ({
          platform: t.platform,
          external_asset_id: externalAssetIdFor(t) as string,
          methods: methods.filter((m) => m !== "gallery"),
        }))
        .filter((d) => d.methods.length > 0);

      const gallerySelections = confirmItems.flatMap(({ target, methods }) =>
        methods.includes("gallery")
          ? [{ target, category: galleryCategories[cropKeyFor(target.id, "gallery")] || "EXTERIOR" }]
          : []
      );

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

      // A promotion carries its own coupon code and terms, so destinations
      // with different promotions cannot share one request: Google reads
      // those from the post body, which is per request.
      const offerKey = (targetId: string) =>
        `${offerDetails[cropKeyFor(targetId, "offer")]?.coupon ?? ""}|${
          offerDetails[cropKeyFor(targetId, "offer")]?.terms ?? ""
        }`;
      const groups = new Map<
        string,
        { destinations: typeof postDestinations; coupon: string; terms: string }
      >();
      for (const item of confirmItems) {
        const methods = item.methods.filter((m) => m !== "gallery");
        if (methods.length === 0) continue;
        const dest = {
          platform: item.target.platform,
          external_asset_id: externalAssetIdFor(item.target) as string,
          methods,
        };
        const details = offerDetails[cropKeyFor(item.target.id, "offer")];
        const key = methods.includes("offer")
          ? `${details?.coupon ?? ""}|${details?.terms ?? ""}`
          : "";
        const group = groups.get(key);
        if (group) group.destinations.push(dest);
        else
          groups.set(key, {
            destinations: [dest],
            coupon: details?.coupon ?? "",
            terms: details?.terms ?? "",
          });
      }

      for (const [groupKey, group] of groups) {
        await apiFetch("/api/v1/channels/publish", {
          method: "POST",
          body: JSON.stringify({
            media_url: mediaUrl,
            media_key: mediaKey,
            media_type: mediaType,
            caption,
            description,
            cta_type: ctaType || null,
            cta_url:
              ctaType && ctaType !== "call" ? ctaUrl.trim() || null : null,
            scheduled_at: scheduleOn && scheduleAt ? new Date(scheduleAt).toISOString() : null,
            delete_at: removeOn && removeAt ? new Date(removeAt).toISOString() : null,
            start_date: startDate ? new Date(startDate).toISOString() : null,
            end_date: endDate ? new Date(endDate).toISOString() : null,
            coupon_code: group.coupon || null,
            terms_conditions: group.terms || null,
            // Google labels the post with the language the merchant wrote
            // it in, so an Arabic post is not published as English.
            language_code: GOOGLE_POST_LANGUAGE[locale] ?? "en-US",
            destinations: group.destinations,
            batch_id: attempt.key,
            idempotency_key: `${attempt.key}:${groupKey}`,
          }),
        });
      }

      // A gallery photo that fails must not roll back the posts that already
      // went out, and must not stop the other locations: each destination is
      // reported on its own.
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
        if (media?.file) {
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

      if (galleryErrors.length) {
        // The draft stays open so the merchant can pick another category and
        // retry; the posts are not re-queued (same idempotency key).
        setPublishError(galleryErrors.join(" · "));
        setGalleryFallbacks(fallbacks);
        return;
      }
      if (fallbacks.length) {
        setGalleryFallbacks(fallbacks);
        onNotice?.(fallbacks.join(" "));
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
      setStartDate("");
      setEndDate("");
      setFormats({});
      setGalleryCategories({});
      setOfferDetails({});
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
    document.getElementById(`dest-row-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  // The modal target + method
  const modalTarget = modalCtx ? findTargetById(modalCtx.targetId) : null;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="shrink-0 border-b border-[var(--ui-line)] px-4 py-4 sm:px-6">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="mb-2 inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--ui-ink-2)] transition hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {pc.back}
          </button>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className={`text-[20px] font-bold ${INK}`}>{pc.title}</h1>
            <p className={`mt-0.5 text-[13px] ${INK2}`}>
              {pc.sub}
            </p>
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-6xl gap-5 px-4 pb-28 pt-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start">
          {/* Below lg the wrappers are display:contents, so the sections
              become one ordered column: 1 → 2 → 3 → formats → 4 → preview. */}
          <div className="contents lg:col-start-1 lg:block lg:space-y-5">
          <section aria-labelledby="publish-media-h" className="ui-panel order-1 bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-media-h" className={`text-[14px] font-bold ${INK}`}>
              {pc.stepMedia}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
              {pc.mediaSub}
            </p>
            <MediaSink media={media} onPick={pickMedia} onClear={clearMedia} thumb={thumb} thumbLabel={thumbLabel} />
          </section>

          <section aria-labelledby="publish-message-h" className="ui-panel order-2 bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-message-h" className={`text-[14px] font-bold ${INK}`}>
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
                    className="mt-1.5 rounded-[10px] border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-[12px] font-medium text-amber-700 dark:text-amber-400"
                  >
                    {fill(pc.truncates, { names: captionOver.map((t) => fill(pc.truncName, { name: PLATFORM_META[t.platform].label, max: fmt(PLATFORM_META[t.platform].captionMax) })).join(" · ") })}
                  </p>
                )}
              </div>
              <div>
                <div className="flex items-baseline justify-between">
                  <label htmlFor="pub-description" className={`text-[12px] font-semibold ${INK2}`}>
                    {pc.description}
                  </label>
                  <span className={`text-[11px] ${INK2}`}>{fmt(description.length)}</span>
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
              </div>
              <div className="mt-4 border-t border-[var(--ui-line)] pt-3">
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
                  className={`${FIELD} mt-1 w-full sm:w-64`}
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
                <p className={`mt-1.5 text-[11px] ${INK2}`}>{pc.ctaHint}</p>
              </div>
            </div>
          </section>

          <section aria-labelledby="publish-schedule-h" className="ui-panel order-5 bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-schedule-h" className={`text-[14px] font-bold ${INK}`}>
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
            {needsEventWindow && (
              <div className="mt-3 border-t border-[var(--ui-line)] pt-3">
                <p className={`mb-2 text-[12px] font-semibold ${INK2}`}>
                  {pc.eventWindow}
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <label className={`flex items-center gap-2 text-[12px] ${INK2}`}>
                    {pc.eventStart}
                    <input
                      type="datetime-local"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      aria-label={pc.eventStart}
                      min={minLocalInput()}
                      className={`${FIELD} w-full sm:w-56`}
                    />
                  </label>
                  <label className={`flex items-center gap-2 text-[12px] ${INK2}`}>
                    {pc.eventEnd}
                    <input
                      type="datetime-local"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      aria-label={pc.eventEnd}
                      min={startDate || minLocalInput()}
                      className={`${FIELD} w-full sm:w-56`}
                    />
                  </label>
                </div>
                <p className={`mt-1.5 text-[11px] ${INK2}`}>{pc.eventWindowHint}</p>
              </div>
            )}
          </section>

          <section aria-labelledby="publish-preview-h" className="ui-panel order-6 bg-[var(--ui-surface)] p-4 sm:p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="publish-preview-h" className={`text-[14px] font-bold ${INK}`}>
                {pc.stepPreview}
              </h2>
              <p className={`text-[12px] ${INK2}`} role="status">
                {mirrorTarget && mirrorMethod
                  ? fill(pc.mirroring, { name: mirrorTarget.name, method: methodLabel(mirrorMethod) })
                  : (
                    <>
                      <span className="lg:hidden">{pc.mirrorNoneWide}</span>
                      <span className="hidden lg:inline">{pc.mirrorNoneSide}</span>
                    </>
                  )}
              </p>
            </div>
            <div className="mt-3">
              <DestinationPreview
                target={mirrorTarget}
                method={mirrorMethod ?? "post"}
                media={media ?? { type: null, url: "" }}
                caption={caption}
                description={description}
                crop={mirrorCrop}
              />
            </div>
          </section>

          </div>

          <aside className="contents lg:col-start-2 lg:block lg:space-y-5 lg:sticky lg:top-4 lg:h-fit">
          <section aria-labelledby="publish-dest-h" className="ui-panel order-3 bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="publish-dest-h" className={`text-[14px] font-bold ${INK}`}>
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
          </section>

          {/* Configure formats — method pills per selected destination */}
          {selectedTargets.length > 0 && (
            <section aria-labelledby="publish-formats-h" className="ui-panel order-4 bg-[var(--ui-surface)] p-4 sm:p-5">
              <h2 id="publish-formats-h" className={`text-[14px] font-bold ${INK}`}>
                {pc.formatsTitle}
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                {pc.formatsSub}
              </p>
              {selectedTargets.some((t) =>
                availableFor(t).some((m) => m === "profile" || m === "banner" || m === "gallery"),
              ) && (
                <p className={`mb-3 text-[11px] ${INK2}`}>
                  {pc.formatsNote} Gallery photos are added to the location&apos;s photo gallery — pick a category when you configure it.
                </p>
              )}
              <div className="space-y-3">
                {selectedTargets.map((t) => {
                  const avail = availableFor(t);
                  const chosen = chosenFor(t);
                  return (
                    <div key={t.id} id={`dest-row-${t.id}`} className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3">
                      <div className="flex items-center gap-2">
                        <PlatformMark platform={t.platform} size={14} />
                        <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--ui-ink)]">{t.name}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {avail.map((m) => {
                          const isOn = chosen.includes(m);
                          const key = cropKeyFor(t.id, m);
                          const isConfigured = configured.has(key);
                          const crop = crops[key] ?? defaultCropFor(t.platform, m);
                          return (
                            <button
                              key={m}
                              type="button"
                              onClick={() => {
                                // Clicking an unselected format selects it and
                                // opens its crop editor; clicking a selected one
                                // removes it (and closes the editor if it was open).
                                toggleFormat(t, m);
                                if (isOn) {
                                  if (modalCtx?.targetId === t.id && modalCtx?.method === m) {
                                    cancelConfig();
                                  }
                                } else {
                                  openConfig(t, m);
                                }
                              }}
                              className={`inline-flex items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                                isOn
                                  ? "border-[var(--ui-ink)] bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                                  : "border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink-2)] hover:bg-[var(--ui-line)]"
                              }`}
                            >
                              <FormatThumb media={media} crop={crop} />
                              {isOn && isConfigured && <span aria-hidden>✓</span>}
                              {methodLabel(m)}
                            </button>
                          );
                        })}
                        <button
                          type="button"
                          onClick={() => toggleAllFormats(t)}
                          className="inline-flex items-center gap-1 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                          title={pc.allTitle}
                        >
                          {pc.allPill}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          <section aria-labelledby="ai-video-h" className="ui-panel order-7 bg-[var(--ui-surface)] p-4 sm:p-5">
            <h2 id="ai-video-h" className={`text-[14px] font-bold ${INK}`}>
              {pc.aiTitle}
            </h2>
            <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
              {pc.aiSub}
            </p>
            <AiVideoCreator googleTargets={googleTargets} />
          </section>
          </aside>
        </div>
      </div>

      {/* Sticky action bar */}
      <div className="sticky bottom-0 z-10 border-t border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3">
          {selectedTargets.length > 0 && (
            <div className="flex w-full gap-1.5 overflow-x-auto pb-0.5">
              {selectedTargets.map((t) => {
                const fmt = chosenFor(t)[0];
                const ok = !!fmt;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => openRow(t.id)}
                    title={ok ? fill(pc.reviewRow, { name: t.name }) : fill(pc.noFormatRow, { name: t.name })}
                    className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                      ok
                        ? "border-[var(--ui-line)] bg-[var(--ui-sunken)] text-[var(--ui-ink)] hover:bg-[var(--ui-line)]"
                        : "border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                    }`}
                  >
                    <PlatformMark platform={t.platform} size={12} />
                    <span className="max-w-[140px] truncate">{t.name}</span>
                    <span className={ok ? "text-[var(--ui-ink-2)]" : ""}>
                      {fmt ? `${methodLabel(fmt)}` : pc.noFormat}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
          <p className={`min-w-0 flex-1 truncate text-[12px] font-medium ${INK2}`} role="status" aria-live="polite">
            {confirmItems.length === 0
              ? pc.readyNone
              : `${pc.readyPre}${destStr} · ${fmtStr}`}
            {scheduleOn && scheduleAt ? fill(pc.scheduledOn, { date: new Date(scheduleAt).toLocaleString(dateLocale) }) : ""}
          </p>
          {notice && <p className="w-full text-[12px] font-semibold text-red-600 dark:text-red-400 sm:w-auto">{notice}</p>}
          {galleryFallbacks.length > 0 && (
            <div className="w-full sm:w-auto" role="status">
              {galleryFallbacks.map((f) => (
                <p key={f} className="text-[12px] font-medium text-amber-700 dark:text-amber-400">
                  {f}
                </p>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={openConfirm}
            disabled={!canPublish}
            className="rounded-[10px] bg-[var(--ui-ink)] px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {scheduleOn ? pc.reviewSchedule : pc.reviewPublish}
          </button>
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
          <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-[var(--ui-surface)] sm:h-auto sm:max-h-[90dvh] sm:max-w-5xl sm:rounded-[16px] sm:border sm:border-[var(--ui-line)] sm:shadow-2xl">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--ui-line)] p-4 sm:border-0 sm:p-5 sm:pb-0">
              <div>
                <h2 className="text-[15px] font-bold text-[var(--ui-ink)] sm:text-[16px]">
                  {fill(pc.modalTitle, { name: modalTarget.name, method: methodLabel(modalCtx.method) })}
                </h2>
                <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                  {pc.modalSub}
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
                  {modalCtx.method === "offer" && (
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[12px] font-semibold text-[var(--ui-ink)]">
                          {pc.couponLabel}
                        </label>
                        <input
                          type="text"
                          value={draftCoupon}
                          onChange={(e) => setDraftCoupon(e.target.value)}
                          placeholder={pc.couponPh}
                          maxLength={64}
                          className="w-full rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus:border-deep-violet/40"
                        />
                        <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{pc.couponHint}</p>
                      </div>
                      <div>
                        <label className="mb-1 block text-[12px] font-semibold text-[var(--ui-ink)]">
                          {pc.termsLabel}
                        </label>
                        <textarea
                          value={draftTerms}
                          onChange={(e) => setDraftTerms(e.target.value)}
                          placeholder={pc.termsPh}
                          maxLength={300}
                          rows={3}
                          className="w-full rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus:border-deep-violet/40"
                        />
                      </div>
                    </div>
                  )}
                  {modalCtx.method === "gallery" && (
                    <div>
                      <label className="mb-1 block text-[12px] font-semibold text-[var(--ui-ink)]">Gallery category</label>
                      <select
                        value={draftGalleryCategory}
                        onChange={(e) => setDraftGalleryCategory(e.target.value)}
                        className="w-full rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus:border-deep-violet/40"
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
                className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2.5 text-[13px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] sm:py-2"
              >
                {pc.cancel}
              </button>
              <button
                type="button"
                onClick={saveConfig}
                className="rounded-[10px] bg-[var(--ui-ink)] px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] sm:py-2"
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
          className={`absolute top-0.5 h-5 w-5 rounded-full transition-transform ${
            scheduleOn
              ? "translate-x-[18px] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
              : "translate-x-0.5 border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
          }`}
        />
      </span>
      <span className={`text-[13px] font-semibold ${INK}`}>{label}</span>
    </button>
  );
}
