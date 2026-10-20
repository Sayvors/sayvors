"use client";

import { useState } from "react";
import { CROP_ASPECT } from "./CropFrame";
import { METHOD_META, PLATFORM_META, type CropState, type MediaState, type PostMethod, type PublishTarget } from "./types";

/*
 * One preview per destination AND format, laid out the way that network
 * actually shows it. Every variant renders from the same inputs (media +
 * caption + description) so what the tenant reads here is what their
 * audience will see. Crop is visual only — the real pixels get cut at
 * publish time.
 *
 * Overlay note (AGENTS.md): story caption scrims and status tints are
 * solid rgba fills, never gradients.
 */

const PREVIEW_W = 240; // standard preview width — large enough to read

/** The ratio a container shows, "orig" falling back to the network's own. */
function aspectFor(crop: CropState, fallback: number): number {
  return crop.key === "orig" ? fallback : CROP_ASPECT[crop.key];
}

/*
 * CroppedMedia — renders media inside a preview box so it matches the
 * crop frame EXACTLY. It tracks the media's natural dimensions, computes
 * the same cover scale the crop frame uses, and applies the same pan
 * offset scaled to the preview box size. This is what makes the preview
 * an honest mirror of the crop editor.
 */
function CroppedMedia({
  media,
  cropKey,
  zoom,
  offset,
  boxW = PREVIEW_W,
  aspect,
  className = "",
}: {
  media: MediaState;
  cropKey: CropState["key"];
  zoom: number;
  offset: { x: number; y: number };
  boxW?: number;
  aspect: number;
  className?: string;
}) {
  const boxH = aspect > 0 ? Math.round(boxW / aspect) : boxW;
  const [naturalState, setNaturalState] = useState<{ url: string; w: number; h: number } | null>(null);

  const active = cropKey !== "orig" ? cropKey : null;
  const url = media?.url ?? "";
  const natural = naturalState && naturalState.url === url ? { w: naturalState.w, h: naturalState.h } : null;

  if (!media.type) return null;

  if (media.type === "video") {
    if (!active) {
      return (
        <video
          src={media.url}
          muted
          loop
          autoPlay
          playsInline
          className={`h-full w-full object-cover ${className}`}
        />
      );
    }
    // Videos: apply the same transform as images using videoWidth/Height
    const cover = natural ? Math.max(boxW / natural.w, boxH / natural.h) : 1;
    const scale = zoom * cover;
    const s = boxW / 260; // editor→preview scale
    return (
      <video
        src={media.url}
        muted
        loop
        autoPlay
        playsInline
        className={`absolute left-1/2 top-1/2 max-w-none select-none ${className}`}
        style={{
          transform: `translate(-50%, -50%) translate(${offset.x * s}px, ${offset.y * s}px) scale(${scale})`,
        }}
        onLoadedMetadata={(e) => {
          const v = e.currentTarget;
          if (v.videoWidth && v.videoHeight) {
            setNaturalState({ url, w: v.videoWidth, h: v.videoHeight });
          }
        }}
      />
    );
  }

  if (!active) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={media.url}
        alt=""
        className={`h-full w-full object-cover ${className}`}
        onLoad={(e) => {
          const img = e.currentTarget;
          setNaturalState({ url, w: img.naturalWidth, h: img.naturalHeight });
        }}
      />
    );
  }

  if (!natural) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={media.url}
        alt=""
        className={`h-full w-full object-cover ${className}`}
        onLoad={(e) => {
          const img = e.currentTarget;
          setNaturalState({ url, w: img.naturalWidth, h: img.naturalHeight });
        }}
      />
    );
  }

  const cover = Math.max(boxW / natural.w, boxH / natural.h);
  const scale = zoom * cover;
  const s = boxW / 260; // editor box is 260px wide
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src={media.url}
      alt=""
      className={`absolute left-1/2 top-1/2 max-w-none select-none ${className}`}
      style={{
        transform: `translate(-50%, -50%) translate(${offset.x * s}px, ${offset.y * s}px) scale(${scale})`,
      }}
      onLoad={(e) => {
        const img = e.currentTarget;
        setNaturalState({ url, w: img.naturalWidth, h: img.naturalHeight });
      }}
    />
  );
}

function captionOverflow(caption: string, platform: keyof typeof PLATFORM_META): number {
  return Math.max(caption.length - PLATFORM_META[platform].captionMax, 0);
}

/* ── Instagram: feed card for posts ───────────────────────────────── */

function InstagramFeedPreview({
  target,
  media,
  caption,
  crop,
}: {
  target: PublishTarget;
  media: MediaState;
  caption: string;
  crop: CropState;
}) {
  const author = target.handle ? `@${target.handle}` : target.name;
  const aspect = aspectFor(crop, 1);
  const overflow = captionOverflow(caption, "instagram");
  return (
    <div className="mx-auto overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white shadow-sm" style={{ width: PREVIEW_W }}>
      <div className="flex items-center gap-2.5 px-3.5 py-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-[#e0405f] bg-[#f0eaff] text-[11px] font-bold text-[#3a2a5e]">
          {author.charAt(author.startsWith("@") ? 1 : 0).toUpperCase()}
        </span>
        <span className="text-[13px] font-bold text-[#111]">{author}</span>
        <span className="ml-auto text-[12px] text-[#888]">···</span>
      </div>
      <div className="relative w-full overflow-hidden bg-black" style={{ aspectRatio: String(aspect), height: Math.round(PREVIEW_W / aspect) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} boxW={PREVIEW_W} aspect={aspect} />
      </div>
      <div className="px-3.5 py-2.5">
        <p className="flex items-center gap-3.5 text-[14px] text-[#111]">
          <span aria-hidden>&#9825;</span>
          <span aria-hidden>&#128172;</span>
          <span aria-hidden>&#10148;</span>
        </p>
        <p className="mt-2 text-[12px] leading-snug text-[#111]">
          <span className="mr-1.5 font-bold">{author}</span>
          {caption || "Your caption appears here."}
        </p>
        {overflow > 0 && (
          <p className="mt-1.5 text-[10px] font-semibold text-amber-600">
            {overflow} characters past Instagram&apos;s limit
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Facebook: feed card for posts ──────────────────────────────── */

function FacebookFeedPreview({
  target,
  media,
  caption,
  description,
  crop,
}: {
  target: PublishTarget;
  media: MediaState;
  caption: string;
  description: string;
  crop: CropState;
}) {
  const aspect = aspectFor(crop, 1.91);
  return (
    <div className="mx-auto overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white shadow-sm" style={{ width: PREVIEW_W }}>
      <div className="flex items-center gap-2.5 px-3.5 pt-3 pb-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#e7f3ff] text-[14px] font-bold text-[#0a66c2]">
          {(target.name || "P").charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-bold text-[#111]">{target.name}</span>
          <span className="block text-[11px] text-[#65676b]">Just now · &#127760;</span>
        </span>
      </div>
      {(caption || description) && (
        <p className="px-3.5 pb-2 text-[12px] leading-snug text-[#111]">
          {caption || description || "Your message appears here."}
        </p>
      )}
      <div className="relative w-full overflow-hidden bg-black" style={{ aspectRatio: String(aspect), height: Math.round(PREVIEW_W / aspect) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} boxW={PREVIEW_W} aspect={aspect} />
      </div>
      <div className="flex items-center justify-between border-t border-[#e4e6eb] px-3.5 py-2 text-[11px] font-semibold text-[#65676b]">
        <span>&#128077; &#10084;&#65039; &#128293;</span>
        <span>Share &rsaquo;</span>
      </div>
    </div>
  );
}

/* ── WhatsApp: status viewer ─────────────────────────────────────── */

function WhatsAppStatusPreview({
  target,
  media,
  caption,
  crop,
}: {
  target: PublishTarget;
  media: MediaState;
  caption: string;
  crop: CropState;
}) {
  const name = target.name || "Your number";
  const aspect = aspectFor(crop, 9 / 16);
  return (
    <div className="mx-auto overflow-hidden rounded-[16px] bg-[#eae6df] shadow-sm" style={{ width: PREVIEW_W - 20 }}>
      <div className="flex items-center gap-2.5 bg-white px-3 py-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-full border-2 border-[#25d366] bg-[#efeae2] text-[12px] font-bold text-[#075e54]">
          {name.charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold text-[#111b21]">{name}</span>
          <span className="block text-[11px] text-[#667781]">My status · public update</span>
        </span>
      </div>
      <div className="p-2" style={{ backgroundColor: "#efeae2" }}>
        <div className="relative mx-auto overflow-hidden rounded-[10px] bg-black" style={{ aspectRatio: String(aspect), width: PREVIEW_W - 40, height: Math.round((PREVIEW_W - 40) / aspect) }}>
          <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} boxW={PREVIEW_W - 40} aspect={aspect} />
          {media.type && (
            <>
              <div aria-hidden className="pointer-events-none absolute left-2 right-2 top-2 flex gap-1">
                <span className="h-[2px] flex-1 rounded-full bg-white" />
                <span className="h-[2px] flex-1 rounded-full bg-white/40" />
              </div>
              <span
                aria-hidden
                className="pointer-events-none absolute right-2 top-4 flex h-6 w-6 items-center justify-center rounded-full bg-[rgba(0,0,0,0.45)] text-[11px] text-white"
              >
                &#128065;
              </span>
              <p className="absolute bottom-0 left-0 right-0 bg-[rgba(0,0,0,0.55)] px-2.5 py-2 text-[11px] leading-snug text-white">
                {caption || "Your status text appears here."}
              </p>
            </>
          )}
          {!media.type && (
            <p className="absolute inset-0 flex items-center justify-center px-3 text-center text-[11px] font-semibold text-white/60">
              Add media — statuses frame 9:16
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Shared vertical chrome: IG/FB stories and reels ──────────────── */

function StoryChrome({
  viewerLabel,
  initialSource,
  media,
  caption,
  crop,
  kind,
}: {
  viewerLabel: string;
  initialSource: string;
  media: MediaState;
  caption: string;
  crop: CropState;
  kind: "story" | "reel";
}) {
  const aspect = aspectFor(crop, 9 / 16);
  const boxW = 200;
  const boxH = aspect > 0 ? Math.round(boxW / aspect) : boxW;
  return (
    <div className="mx-auto overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-black shadow-sm relative" style={{ width: boxW, height: boxH }}>
      <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} boxW={boxW} aspect={aspect} />
      {media.type && (
        <>
          <div aria-hidden className="pointer-events-none absolute left-2.5 right-2.5 top-2.5 flex gap-1">
            <span className="h-[2.5px] flex-1 rounded-full bg-white" />
            <span className="h-[2.5px] flex-1 rounded-full bg-white/40" />
          </div>
          <div className="pointer-events-none absolute left-2.5 right-2.5 top-6 flex items-center gap-2">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/60 bg-[rgba(0,0,0,0.45)] text-[10px] font-bold text-white">
              {initialSource.charAt(0).toUpperCase()}
            </span>
            <span className="truncate text-[11px] font-bold text-white">{viewerLabel}</span>
            <span className="ml-auto text-[11px] font-bold text-white/70">&#10005;</span>
          </div>
          <span className="pointer-events-none absolute right-2.5 top-12 rounded-full bg-[rgba(0,0,0,0.5)] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white/90">
            {kind === "reel" ? "Reel" : "Story"}
          </span>
          {caption && (
            <p className="absolute bottom-0 left-0 right-0 bg-[rgba(0,0,0,0.55)] px-2.5 py-2 text-[11px] leading-snug text-white">
              {caption}
            </p>
          )}
        </>
      )}
      {!media.type && (
        <p className="absolute inset-0 flex items-center justify-center px-4 text-center text-[11px] font-semibold text-white/60">
          Add media — this format frames 9:16
        </p>
      )}
    </div>
  );
}

/* ── Google Business Profile: post card on Search & Maps ──────────── */

function GooglePostPreview({
  target,
  media,
  caption,
  description,
  crop,
}: {
  target: PublishTarget;
  media: MediaState;
  caption: string;
  description: string;
  crop: CropState;
}) {
  const author = target.name || "Your business";
  const aspect = aspectFor(crop, 1.91);
  const body = caption || description || "Your update appears on Google Search & Maps.";
  const overflow = captionOverflow(caption, "google_reviews");
  return (
    <div className="mx-auto overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white shadow-sm" style={{ width: PREVIEW_W }}>
      <div className="flex items-center gap-2.5 px-3.5 py-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-[#4285f4] bg-[#eef5ff] text-[11px] font-bold text-[#1a0dab]">
          {author.charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-bold text-[#111]">{author}</span>
          <span className="block text-[11px] text-[#65676b]">On Google · just now</span>
        </span>
      </div>
      {body && (
        <p className="px-3.5 pt-2 pb-1 text-[12px] leading-snug text-[#111]">
          {body}
        </p>
      )}
      <div className="relative w-full overflow-hidden bg-black" style={{ aspectRatio: String(aspect), height: Math.round(PREVIEW_W / aspect) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} boxW={PREVIEW_W} aspect={aspect} />
      </div>
      <div className="flex items-center justify-between border-t border-[#e4e6eb] px-3.5 py-2 text-[11px] font-semibold text-[#65676b]">
        <span className="flex items-center gap-1">
          <span aria-hidden>&#128077;</span>
          <span>Google Post</span>
        </span>
        <span>Search &amp; Maps &rsaquo;</span>
      </div>
      {overflow > 0 && (
        <p className="mt-1 px-3.5 text-[10px] font-semibold text-amber-600">
          {overflow} characters past Google&apos;s limit
        </p>
      )}
    </div>
  );
}

/* ── Generic fallback for the neutral main preview + later networks ─ */

function GenericPreview({
  label,
  media,
  caption,
  description,
  crop,
}: {
  label: string;
  media: MediaState;
  caption: string;
  description: string;
  crop: CropState;
}) {
  const aspect = aspectFor(crop, 4 / 3);
  return (
    <div className="mx-auto overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-white shadow-sm" style={{ width: PREVIEW_W }}>
      <div className="flex items-center gap-2.5 px-3.5 py-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--ui-sunken)] text-[12px] font-bold text-[var(--ui-ink)]">
          &#10022;
        </span>
        <span className="text-[13px] font-bold text-[#111]">{label}</span>
      </div>
      <div className="relative w-full overflow-hidden bg-black" style={{ aspectRatio: String(aspect), height: Math.round(PREVIEW_W / aspect) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} boxW={PREVIEW_W} aspect={aspect} />
      </div>
      {caption && <p className="px-3.5 py-2.5 text-[12px] leading-snug text-[#111]">{caption}</p>}
      {!caption && description && <p className="px-3.5 py-2.5 text-[12px] leading-snug text-[#111]">{description}</p>}
    </div>
  );
}

/* ── Registry ─────────────────────────────────────────────────────── */

export default function DestinationPreview({
  target,
  method = "post",
  media,
  caption,
  description,
  crop,
}: {
  target: PublishTarget | null;
  method?: PostMethod;
  media: MediaState;
  caption: string;
  description: string;
  crop: CropState;
}) {
  if (target) {
    switch (target.platform) {
      case "instagram":
        return method === "post" ? (
          <InstagramFeedPreview target={target} media={media} caption={caption} crop={crop} />
        ) : (
          <StoryChrome
            kind={method === "story" ? "story" : "reel"}
            viewerLabel={target.handle ? `@${target.handle}` : target.name}
            initialSource={target.name || "ig"}
            media={media}
            caption={caption}
            crop={crop}
          />
        );
      case "facebook":
        return method === "post" ? (
          <FacebookFeedPreview
            target={target}
            media={media}
            caption={caption}
            description={description}
            crop={crop}
          />
        ) : (
          <StoryChrome
            kind={method === "story" ? "story" : "reel"}
            viewerLabel={target.name}
            initialSource={target.name || "fb"}
            media={media}
            caption={caption}
            crop={crop}
          />
        );
      case "whatsapp":
        return <WhatsAppStatusPreview target={target} media={media} caption={caption} crop={crop} />;
      case "google_reviews":
        return <GooglePostPreview target={target} media={media} caption={caption} description={description} crop={crop} />;
      default:
        return (
          <GenericPreview
            label={`${target.name} · ${METHOD_META[method].label}`}
            media={media}
            caption={caption}
            description={description}
            crop={crop}
          />
        );
    }
  }
  return (
    <GenericPreview
      label="How this post reads"
      media={media}
      caption={caption}
      description={description}
      crop={crop}
    />
  );
}
