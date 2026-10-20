"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { INK, INK2 } from "@/components/channels/instagram/ui";
import { apiFetch } from "@/lib/api-rag";
import { externalAssetIdFor } from "@/lib/publish-targets";
import MediaSink from "./MediaSink";
import DestinationSelector from "./DestinationSelector";
import DestinationPreview from "./DestinationPreview";
import ConfirmModal from "./ConfirmModal";
import CropFrame from "./CropFrame";
import FormatThumb from "./FormatThumb";
import {
  DEFAULT_CROP,
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

export default function PublishComposer({
  onPublished,
  onCancel,
}: {
  onPublished?: () => void;
  onCancel?: () => void;
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

  const blobRef = useRef<string | null>(null);

  // ── Publishing ──────────────────────────────────────────────────
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  // ── Schedule ────────────────────────────────────────────────────
  const [scheduleOn, setScheduleOn] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");

  // ── Per-format previews + saved crops ───────────────────────────
  const [crops, setCrops] = useState<Record<string, CropState>>({});
  /** destination+format currently being edited in the modal */
  const [modalCtx, setModalCtx] = useState<{ targetId: string; method: PostMethod } | null>(null);
  /** draft crop being edited in the modal (committed on Save) */
  const [draftCrop, setDraftCrop] = useState<CropState>(DEFAULT_CROP);
  /** formats that have been explicitly saved */
  const [configured, setConfigured] = useState<Set<string>>(new Set());

  /** Per-destination chosen formats */
  const [formats, setFormats] = useState<Record<string, PostMethod[]>>({});

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

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
      // seed crop default if not present
      const key = cropKeyFor(t.id, m);
      setCrops((prev) => (prev[key] ? prev : { ...prev, [key]: defaultCropFor(t.platform, m) }));
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
  const openConfig = (t: PublishTarget, m: PostMethod) => {
    const key = cropKeyFor(t.id, m);
    setDraftCrop(crops[key] ?? defaultCropFor(t.platform, m));
    setModalCtx({ targetId: t.id, method: m });
  };

  const saveConfig = () => {
    if (!modalCtx) return;
    const t = targets.find((x) => x.id === modalCtx.targetId);
    if (!t) return;
    const key = cropKeyFor(modalCtx.targetId, modalCtx.method);
    setCrops((prev) => ({ ...prev, [key]: draftCrop }));
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
  const formatCount = confirmItems.reduce((n, i) => n + i.methods.length, 0);
  // The publish endpoint requires a fetchable media URL, and WhatsApp's only
  // format (status) is media-only — a text-only push would fail downstream,
  // so media is required at the gate too.
  const canPublish = confirmItems.length > 0 && media !== null;

  const openConfirm = () => {
    if (media === null) {
      setNotice("Attach an image or video — text-only publishing isn't supported yet.");
      return;
    }
    if (confirmItems.length === 0) {
      setNotice("Pick a destination with at least one format.");
      return;
    }
    setNotice(null);
    setPublishError(null);
    setConfirmOpen(true);
  };

  const publishNow = async () => {
    if (!media || publishing) return;
    setPublishing(true);
    setPublishError(null);
    try {
      // Locally-picked files must go to our storage first: providers (and
      // the Google Business uploader) fetch the media from a public URL at
      // publish time, so a blob: URL can never be delivered.
      let mediaUrl = media.url;
      let mediaKey = media.key ?? null;
      if (media.url.startsWith("blob:")) {
        if (!media.file) throw new Error("The picked file is no longer available — attach it again.");
        const form = new FormData();
        form.append("file", media.file);
        const up = await apiFetch("/api/v1/media/upload", { method: "POST", body: form });
        mediaUrl = up.image_url;
        mediaKey = up.key ?? null;
        if (!mediaUrl) throw new Error("Upload succeeded but no URL came back — try a different file.");
      }

      const batchId = crypto.randomUUID();
      // One idempotency key per attempt so a retry (network drop, 500) never
      // double-posts: the backend keys jobs as key:platform:method.
      const destinations = confirmItems.map(({ target: t, methods }) => ({
        platform: t.platform,
        external_asset_id: externalAssetIdFor(t) as string,
        methods,
      }));

      await apiFetch("/api/v1/channels/publish", {
        method: "POST",
        body: JSON.stringify({
          media_url: mediaUrl,
          media_key: mediaKey,
          media_type: media.type,
          caption,
          description,
          scheduled_at: scheduleOn && scheduleAt ? new Date(scheduleAt).toISOString() : null,
          destinations,
          batch_id: batchId,
          idempotency_key: `${batchId}:${Date.now()}`,
        }),
      });

      setConfirmOpen(false);
      clearMedia();
      setCaption("");
      setDescription("");
      setScheduleOn(false);
      setScheduleAt("");
      setFormats({});
      onPublished?.();
    } catch (e) {
      setPublishError(e instanceof Error ? e.message : "Publishing failed — try again.");
    } finally {
      setPublishing(false);
    }
  };

  // ── What's being edited (mirrors) ───────────────────────────────
  const activeTarget = modalCtx ? targets.find((t) => t.id === modalCtx.targetId) ?? null : null;
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
      ? `${PLATFORM_META[mirrorTarget.platform].label} · ${METHOD_META[mirrorMethod].label}`
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
  const modalTarget = modalCtx ? targets.find((t) => t.id === modalCtx.targetId) ?? null : null;

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
            ← Back to posts
          </button>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className={`text-[20px] font-bold ${INK}`}>Publish a post</h1>
            <p className={`mt-0.5 text-[13px] ${INK2}`}>
              One post, every connected network — pick a format on any destination to configure its crop.
            </p>
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-6xl gap-5 px-4 pb-28 pt-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          {/* ── left / main ── */}
          <div className="space-y-5">
            {/* 1 · Media */}
            <section aria-labelledby="publish-media-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-media-h" className={`text-[14px] font-bold ${INK}`}>
                1 · Media
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                An image or video is required — the frame mirrors the format you&apos;re configuring.
              </p>
              <MediaSink media={media} onPick={pickMedia} onClear={clearMedia} thumb={thumb} thumbLabel={thumbLabel} />
            </section>

            {/* 2 · Message */}
            <section aria-labelledby="publish-message-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-message-h" className={`text-[14px] font-bold ${INK}`}>
                2 · Message
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                Caption is the hook every network shows; description is the longer body.
              </p>
              <div className="space-y-3">
                <div>
                  <div className="flex items-baseline justify-between">
                    <label htmlFor="pub-caption" className={`text-[12px] font-semibold ${INK2}`}>
                      Caption
                    </label>
                    <span
                      className={`text-[11px] ${
                        caption.length > captionLimit ? "font-semibold text-amber-600 dark:text-amber-400" : INK2
                      }`}
                    >
                      {caption.length} / {captionLimit.toLocaleString("en-US")}
                    </span>
                  </div>
                  <textarea
                    id="pub-caption"
                    value={caption}
                    onChange={(e) => setCaption(e.target.value)}
                    rows={2}
                    maxLength={PLATFORM_META.facebook.captionMax}
                    placeholder="Say it in one line…"
                    className={`${FIELD} mt-1 w-full resize-y`}
                  />
                  {showCaptionWarn && (
                    <p
                      role="status"
                      className="mt-1.5 rounded-[10px] border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-[12px] font-medium text-amber-700 dark:text-amber-400"
                    >
                      ⚠ Truncates on:{" "}
                      {captionOver
                        .map((t) => `${PLATFORM_META[t.platform].label} (${PLATFORM_META[t.platform].captionMax.toLocaleString("en-US")})`)
                        .join(" · ")}
                    </p>
                  )}
                </div>
                <div>
                  <div className="flex items-baseline justify-between">
                    <label htmlFor="pub-description" className={`text-[12px] font-semibold ${INK2}`}>
                      Description
                    </label>
                    <span className={`text-[11px] ${INK2}`}>{description.length}</span>
                  </div>
                  <textarea
                    id="pub-description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={4}
                    maxLength={PLATFORM_META.facebook.captionMax}
                    placeholder="The full story — offer details, event info, the works."
                    className={`${FIELD} mt-1 w-full resize-y`}
                  />
                </div>
              </div>
            </section>

            {/* 4 · When */}
            <section aria-labelledby="publish-schedule-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-schedule-h" className={`text-[14px] font-bold ${INK}`}>
                4 · When
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>Optional — leave it off to publish immediately.</p>
              <div className="flex flex-wrap items-center gap-3">
                <ScheduleToggle scheduleOn={scheduleOn} setScheduleOn={setScheduleOn} />
                {scheduleOn && (
                  <input
                    type="datetime-local"
                    value={scheduleAt}
                    onChange={(e) => setScheduleAt(e.target.value)}
                    aria-label="Publish at"
                    className={`${FIELD} w-full sm:w-64`}
                  />
                )}
              </div>
            </section>

            {/* Live preview */}
            <section aria-labelledby="publish-preview-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="publish-preview-h" className={`text-[14px] font-bold ${INK}`}>
                  Live preview
                </h2>
                <p className={`text-[12px] ${INK2}`} role="status">
                  {mirrorTarget && mirrorMethod
                    ? `Mirroring ${mirrorTarget.name} · ${METHOD_META[mirrorMethod].label}`
                    : "Pick a format on the right to configure it"}
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

          {/* ── right / aside ── */}
          <aside className="space-y-5 lg:sticky lg:top-4 lg:h-fit">
            {/* 3 · Where it goes */}
            <section aria-labelledby="publish-dest-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-dest-h" className={`text-[14px] font-bold ${INK}`}>
                3 · Where it goes
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                Flip the master switch for every network, or hand-pick below.
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
              <section aria-labelledby="publish-formats-h" className="ui-panel bg-[var(--ui-surface)] p-5">
                <h2 id="publish-formats-h" className={`text-[14px] font-bold ${INK}`}>
                  Configure formats
                </h2>
                <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                  Click a format to set its crop and thumbnail.
                </p>
                {selectedTargets.some((t) =>
                  availableFor(t).some((m) => m === "profile" || m === "banner"),
                ) && (
                  <p className={`mb-3 text-[11px] ${INK2}`}>
                    A profile picture or banner replaces that image on the
                    account — it carries no caption, and it can only be
                    changed by publishing a new one.
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
                                  if (!isOn) {
                                    toggleFormat(t, m);
                                  }
                                  openConfig(t, m);
                                }}
                                className={`inline-flex items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                                  isConfigured
                                    ? "border-[var(--ui-ink)] bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                                    : isOn
                                    ? "border-[var(--ui-line-strong)] bg-[var(--ui-surface)] text-[var(--ui-ink)] hover:bg-[var(--ui-line)]"
                                    : "border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink-2)] hover:bg-[var(--ui-line)]"
                                }`}
                              >
                                <FormatThumb media={media} crop={crop} />
                                {isConfigured && <span aria-hidden>✓</span>}
                                {METHOD_META[m].label}
                              </button>
                            );
                          })}
                          <button
                            type="button"
                            onClick={() => toggleAllFormats(t)}
                            className="inline-flex items-center gap-1 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                            title="Select every feed format for this destination"
                          >
                            All
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
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
                    title={ok ? `Review ${t.name}` : `${t.name} has no format yet`}
                    className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
                      ok
                        ? "border-[var(--ui-line)] bg-[var(--ui-sunken)] text-[var(--ui-ink)] hover:bg-[var(--ui-line)]"
                        : "border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                    }`}
                  >
                    <PlatformMark platform={t.platform} size={12} />
                    <span className="max-w-[140px] truncate">{t.name}</span>
                    <span className={ok ? "text-[var(--ui-ink-2)]" : ""}>
                      {fmt ? `${METHOD_META[fmt].label}` : "no format"}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
          <p className={`min-w-0 flex-1 truncate text-[12px] font-medium ${INK2}`} role="status" aria-live="polite">
            {confirmItems.length === 0
              ? "No destination with a format selected yet."
              : `Ready for ${confirmItems.length} destination${confirmItems.length === 1 ? "" : "s"} · ${formatCount} format${formatCount === 1 ? "" : "s"}.`}
            {scheduleOn && scheduleAt ? ` · Scheduled ${new Date(scheduleAt).toLocaleString()}` : ""}
          </p>
          {notice && <p className="w-full text-[12px] font-semibold text-red-600 dark:text-red-400 sm:w-auto">{notice}</p>}
          <button
            type="button"
            onClick={openConfirm}
            disabled={!canPublish}
            className="rounded-[10px] bg-[var(--ui-ink)] px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {scheduleOn ? "Review schedule" : "Review & publish"}
          </button>
        </div>
      </div>

      {/* Configuration modal — opens when a format pill is clicked */}
      {modalCtx && modalTarget && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Configure ${modalTarget.name} · ${METHOD_META[modalCtx.method].label}`}
          onClick={(e) => {
            if (e.target === e.currentTarget) cancelConfig();
          }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(0,0,0,0.45)] p-4"
        >
          <div className="w-full max-w-5xl rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[16px] font-bold text-[var(--ui-ink)]">
                  Configure {modalTarget.name} · {METHOD_META[modalCtx.method].label}
                </h2>
                <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
                  Crop and frame this format. Saves when you hit Save.
                </p>
              </div>
              <button
                type="button"
                onClick={cancelConfig}
                aria-label="Close"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-bold text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
              >
                ×
              </button>
            </div>

            <div className="mt-4 flex flex-col items-center gap-5 sm:flex-row sm:items-start sm:justify-center sm:gap-8">
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
              <div className="w-full max-w-[320px] shrink-0">
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

            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={cancelConfig}
                className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[13px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveConfig}
                className="rounded-[10px] bg-[var(--ui-ink)] px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
              >
                Save {METHOD_META[modalCtx.method].label}
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
}: {
  scheduleOn: boolean;
  setScheduleOn: (v: boolean) => void;
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
      <span className={`text-[13px] font-semibold ${INK}`}>Schedule for later</span>
    </button>
  );
}
