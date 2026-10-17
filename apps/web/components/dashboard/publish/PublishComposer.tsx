"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { INK, INK2 } from "@/components/channels/instagram/ui";
import MediaSink from "./MediaSink";
import DestinationSelector from "./DestinationSelector";
import DestinationPreview from "./DestinationPreview";
import ConfirmModal from "./ConfirmModal";
import { DEFAULT_CROP, PLATFORM_META, type CropState, type MediaState, type PublishTarget } from "./types";
import CropFrame from "./CropFrame";

/*
 * The unified Publish composer.
 *
 * Left rail: what to say (media, caption, description), where to say it
 * (all connected / selected), when (schedule). Right rail: a main preview
 * plus one expandable per-network preview with a visual crop for each.
 *
 * Everything here is local state — the publish endpoint hasn't landed.
 * The confirm modal says so explicitly rather than faking success.
 */

const DEMO_TARGETS: PublishTarget[] = [
  { id: "demo:instagram", platform: "instagram", name: "Sayvors Studio", handle: "sayvors.studio", demo: true },
  { id: "demo:facebook", platform: "facebook", name: "Sayvors Page", demo: true },
  { id: "demo:whatsapp", platform: "whatsapp", name: "+91 98••• •••12", demo: true },
];

const FIELD =
  "rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]";

export default function PublishComposer() {
  // ── Destinations ─────────────────────────────────────────────────
  const [targets, setTargets] = useState<PublishTarget[]>([]);
  const [targetsStatus, setTargetsStatus] = useState<"loading" | "ready" | "error">("loading");
  const [allConnected, setAllConnected] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { fetchMetaAssets } = await import("@/lib/api-meta");
      const providers = ["facebook", "instagram", "whatsapp"] as const;
      const results = await Promise.allSettled(providers.map((p) => fetchMetaAssets(p)));
      if (cancelled) return;
      const rows: PublishTarget[] = [];
      providers.forEach((provider, i) => {
        const r = results[i];
        const assets = r.status === "fulfilled" ? r.value.assets ?? [] : [];
        const active = assets.filter((a) => a.active);
        if (provider === "whatsapp") {
          active
            .filter((a) => a.asset_type === "phone_number")
            .forEach((a) =>
              rows.push({
                id: `wa:${a.external_asset_id}`,
                platform: "whatsapp",
                name: a.phone ?? a.name ?? "WhatsApp number",
                handle: a.phone ?? null,
              }),
            );
        } else {
          active
            .filter((a) => a.asset_type === "page" || a.asset_type === "account")
            .forEach((a) =>
              rows.push({
                id: `${provider}:${a.external_asset_id}`,
                platform: provider,
                name: a.name ?? a.username ?? a.external_asset_id,
                handle: a.username ?? null,
              }),
            );
          if (r.status === "fulfilled" && active.length === 0) {
            rows.push({ id: `${provider}:empty`, platform: provider, name: PLATFORM_META[provider].label, demo: true });
          }
        }
      });
      setTargets(rows);
      setTargetsStatus("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const usableTargets = useMemo(() => targets.filter((t) => !t.demo), [targets]);

  // ── Media + message ─────────────────────────────────────────────
  const [media, setMedia] = useState<MediaState | null>(null);
  const [caption, setCaption] = useState("");
  const [description, setDescription] = useState("");

  // ── Live media blob url (revoked on replace/unmount) ─────────────
  const blobRef = useRef<string | null>(null);

  // ── Schedule ────────────────────────────────────────────────────
  const [scheduleOn, setScheduleOn] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");

  // ── Per-network previews + crops ────────────────────────────────
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [crops, setCrops] = useState<Record<string, CropState>>({});

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // Sync selection with "all connected": flipping the master selects or
  // clears everything; manual edits turn the master off without touching
  // the individual rows.
  const applyAll = useCallback(
    (v: boolean) => {
      setAllConnected(v);
      setSelected(v ? new Set(usableTargets.map((t) => t.id)) : new Set());
    },
    [usableTargets],
  );

  const toggleTarget = (t: PublishTarget) => {
    setAllConnected(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(t.id)) next.delete(t.id);
      else next.add(t.id);
      // Refill when the last manual pick re-covers every destination so the
      // master switch stays honest rather than one edit away.
      if (usableTargets.length > 0 && next.size === usableTargets.length) {
        setAllConnected(true);
      }
      return next;
    });
  };

  const loadDemo = () => {
    setTargets(DEMO_TARGETS);
    setSelected(new Set(DEMO_TARGETS.map((t) => t.id)));
  };

  const pickMedia = (type: "image" | "video", url: string, fileName?: string, sizeBytes?: number) => {
    if (blobRef.current && blobRef.current !== url) {
      URL.revokeObjectURL(blobRef.current);
    }
    if (url.startsWith("blob:")) blobRef.current = url;
    else blobRef.current = null;
    setMedia({ type, url, fileName, sizeBytes });
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

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const setCrop = (id: string) => (patch: Partial<CropState>) => {
    setCrops((prev) => ({ ...prev, [id]: { ...DEFAULT_CROP, ...prev[id], ...patch } }));
  };

  const selectedTargets = useMemo(
    () => targets.filter((t) => selected.has(t.id)),
    [targets, selected],
  );

  const canPublish = selectedTargets.length > 0 && (media !== null || caption.trim().length > 0 || description.trim().length > 0);

  const openConfirm = () => {
    if (!canPublish) {
      setNotice("Add media or write a caption, and pick at least one destination.");
      return;
    }
    setNotice(null);
    setConfirmOpen(true);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="shrink-0 border-b border-[var(--ui-line)] px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className={`text-[20px] font-bold ${INK}`}>Publish a post</h1>
            <p className={`mt-0.5 text-[13px] ${INK2}`}>
              One post, every connected network — preview it per channel before anything leaves.
            </p>
          </div>
          <p className={`text-[11px] font-semibold uppercase tracking-widest ${INK2}`}>UI preview</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-6xl gap-5 px-4 pb-28 pt-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          {/* ── Left rail: compose ── */}
          <div className="space-y-5">
            {/* Media */}
            <section aria-labelledby="publish-media-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-media-h" className={`text-[14px] font-bold ${INK}`}>
                1 · Media
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>An image, a video, or nothing — the text-only option stays open.</p>
              <MediaSink media={media} onPick={pickMedia} onClear={clearMedia} />
            </section>

            {/* Message */}
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
                    <span className={`text-[11px] ${INK2}`}>{caption.length}</span>
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

            {/* Destinations */}
            <section aria-labelledby="publish-dest-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-dest-h" className={`text-[14px] font-bold ${INK}`}>
                3 · Where it goes
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>
                Smash the master switch for every network, or hand-pick below.
              </p>
              <DestinationSelector
                targets={targets}
                status={targetsStatus}
                allConnected={allConnected}
                selected={selected}
                onSelectAll={applyAll}
                onToggleTarget={toggleTarget}
                onLoadDemo={loadDemo}
              />
            </section>

            {/* Schedule */}
            <section aria-labelledby="publish-schedule-h" className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-schedule-h" className={`text-[14px] font-bold ${INK}`}>
                4 · When
              </h2>
              <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>Optional — leave it off to publish immediately.</p>
              <div className="flex flex-wrap items-center gap-3">
                <Switch2 scheduleOn={scheduleOn} setScheduleOn={setScheduleOn} />
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
          </div>

          {/* ── Right rail: previews ── */}
          <aside className="lg:sticky lg:top-4 lg:h-fit" aria-labelledby="publish-preview-h">
            <section className="ui-panel bg-[var(--ui-surface)] p-5">
              <h2 id="publish-preview-h" className={`text-[14px] font-bold ${INK}`}>
                Preview
              </h2>
              <p className={`mt-0.5 text-[12px] ${INK2}`}>How the post reads everywhere.</p>
              <div className="mt-3">
                <DestinationPreview
                  target={null}
                  media={media ?? { type: null, url: "" }}
                  caption={caption}
                  description={description}
                  crop={crops["main"] ?? DEFAULT_CROP}
                />
              </div>
            </section>

            <section aria-label="Per-network previews" className="mt-4">
              {targets.filter((t) => !t.demo).length > 0 ? (
                <TargetList
                  targets={targets.filter((t) => !t.demo)}
                  selected={selected}
                  expanded={expanded}
                  media={media}
                  caption={caption}
                  description={description}
                  crops={crops}
                  onToggleExpanded={toggleExpanded}
                  onSetCrop={setCrop}
                />
              ) : (
                targetsStatus === "loading" && (
                  <div className="ui-panel space-y-2 bg-[var(--ui-surface)] p-5" aria-hidden>
                    <div className="h-16 animate-pulse rounded-[10px] bg-[var(--ui-sunken)]" />
                    <div className="h-16 animate-pulse rounded-[10px] bg-[var(--ui-sunken)]" />
                    <div className="h-16 animate-pulse rounded-[10px] bg-[var(--ui-sunken)]" />
                  </div>
                )
              )}
            </section>
          </aside>
        </div>
      </div>

      {/* Sticky action bar */}
      <div className="sticky bottom-0 z-10 border-t border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3">
          <p className={`min-w-0 flex-1 truncate text-[12px] font-medium ${INK2}`} role="status" aria-live="polite">
            {selectedTargets.length === 0
              ? "No destination selected yet."
              : `Ready for ${selectedTargets.length} destination${selectedTargets.length === 1 ? "" : "s"}.`}
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

      <ConfirmModal
        open={confirmOpen}
        targets={selectedTargets}
        media={media ?? { type: null, url: "" }}
        captionLen={caption.trim().length}
        descriptionLen={description.trim().length}
        scheduled={scheduleOn && scheduleAt ? scheduleAt : null}
        onClose={() => setConfirmOpen(false)}
      />
    </div>
  );
}

/* ── Inline sub-pieces ───────────────────────────────────────────── */

function Switch2({
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

function TargetList({
  targets,
  selected,
  expanded,
  media,
  caption,
  description,
  crops,
  onToggleExpanded,
  onSetCrop,
}: {
  targets: PublishTarget[];
  selected: Set<string>;
  expanded: Set<string>;
  media: MediaState | null;
  caption: string;
  description: string;
  crops: Record<string, CropState>;
  onToggleExpanded: (id: string) => void;
  onSetCrop: (id: string) => (patch: Partial<CropState>) => void;
}) {
  const nonDemo = targets;

  return (
    <div
      className="ui-panel divide-y divide-[var(--ui-line)] bg-[var(--ui-surface)]"
      role="region"
      aria-label="Per-network previews with crop"
    >
      <p className={`flex flex-wrap items-center gap-x-2 px-5 pb-3 pt-4 text-[12px] font-bold ${INK2}`}>
        <span className="text-[10px] font-bold uppercase tracking-widest">Per-network preview · crop each</span>
      </p>
      <ul>
        {nonDemo.map((t) => {
          const isOpen = expanded.has(t.id);
          const crop = crops[t.id] ?? DEFAULT_CROP;
          const chosen = selected.has(t.id);
          const meta = PLATFORM_META[t.platform];
          return (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => onToggleExpanded(t.id)}
                aria-expanded={isOpen}
                aria-controls={`crop-panel-${t.id}`}
                className="flex w-full items-center gap-2.5 px-5 py-3 text-left transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] focus-visible:-outline-offset-[3px]"
              >
                <PlatformMark platform={t.platform} size={16} />
                <span className="min-w-0 flex-1">
                  <span className={`block truncate text-[13px] font-semibold ${chosen ? INK : INK2}`}>{t.name}</span>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    {meta.label}
                    {chosen ? "" : " · not selected"}
                  </span>
                </span>
                {crop.key !== "orig" && (
                  <span className="shrink-0 rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                    {crop.key}
                  </span>
                )}
                <svg
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  className={`h-3 w-3 shrink-0 text-[var(--ui-ink-2)] transition-transform ${isOpen ? "rotate-180" : ""}`}
                  aria-hidden
                >
                  <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {isOpen && (
                <div id={`crop-panel-${t.id}`} className="border-t border-[var(--ui-line)] bg-[var(--ui-sunken)] px-5 py-4">
                  <div className="mb-3">
                    <DestinationPreview
                      target={t}
                      media={media ?? { type: null, url: "" }}
                      caption={caption}
                      description={description}
                      crop={crop}
                    />
                  </div>
                  <CropSection
                    skuKey={t.id}
                    media={media ? { type: media.type, url: media.url } : null}
                    crop={crop}
                    onCrop={onSetCrop(t.id)}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CropSection({
  skuKey,
  media,
  crop,
  onCrop,
}: {
  skuKey: string;
  media: { type: "image" | "video" | null; url: string } | null;
  crop: CropState;
  onCrop: (patch: Partial<CropState>) => void;
}) {
  if (!media || media.type === null) {
    return (
      <p className="text-[11px] font-semibold text-[var(--ui-ink-2)]">
        Add media on the left to crop it here.
      </p>
    );
  }
  return (
    <CropFrame
      key={skuKey}
      url={media.url}
      type={media.type}
      cropKey={crop.key}
      zoom={crop.zoom}
      offset={{ x: crop.x, y: crop.y }}
      onCropKey={(k) => onCrop({ key: k, zoom: 1, x: 0, y: 0 })}
      onZoom={(z) => onCrop({ zoom: z })}
      onOffset={(o) => onCrop({ x: o.x, y: o.y })}
    />
  );
}

/* ── Small helpers kept local to the composer file ────────────────── */

