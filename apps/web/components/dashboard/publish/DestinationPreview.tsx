"use client";

import PlatformMark from "@/components/channels/PlatformMark";
import { INK2 } from "@/components/channels/instagram/ui";
import type { CropState, MediaState, PublishTarget } from "./types";
import { CROP_ASPECT, CROP_LABEL } from "./CropFrame";

/*
 * One preview per network, laid out the way that network actually shows a
 * post. All of them render from the same inputs (media + caption +
 * description) so what the tenant reads here is what their audience will
 * see, per platform. Crop is visual: the frame clips media with the same
 * object-fit/transform pair the CropFrame uses.
 */

function CroppedMedia({
  media,
  cropKey,
  zoom,
  offset,
  className = "",
}: {
  media: MediaState;
  cropKey: CropState["key"];
  zoom: number;
  offset: { x: number; y: number };
  className?: string;
}) {
  if (!media.type) return null;
  const active = cropKey !== "orig" ? cropKey : null;
  if (media.type === "video") {
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
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src={media.url}
      alt=""
      className={`h-full w-full select-none object-cover ${className}`}
      style={
        active
          ? {
              transform: `scale(${Math.max(zoom, coverFor())}) translate(${offset.x / 6}px, ${offset.y / 6}px)`,
            }
          : undefined
      }
    />
  );
}

// The preview box is narrower than the 260px crop editor, so the editor's
// px offsets are translated down proportionally and a small push-in zoom
// keeps the tenant's chosen framing readable at preview size. object-fit:
// cover already center-crops; translate+scale then re-frames in-window.
function coverFor(): number {
  return 1.08; // slight push-in so the cropped frame reads clearly in previews
}

/* ── Instagram: square/portrait feed card ─────────────────────────── */

function InstagramPreview({
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
  const aspect = crop.key === "orig" ? 1 : CROP_ASPECT[crop.key as Exclude<CropState["key"], "orig">];
  const overflow = Math.max(
    caption.length - PLATFORM_CAP_SAFE("instagram"),
    0,
  );
  return (
    <div className="mx-auto w-full max-w-[232px] overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white">
      <div className="flex items-center gap-2 px-3 py-2">
        <PlatformMark platform="instagram" size={16} />
        <span className="text-[12px] font-bold text-[#111]">{target.handle ? `@${target.handle}` : target.name}</span>
        <span className="ml-auto text-[11px] text-[#888]">···</span>
      </div>
      <div className="w-full bg-black" style={{ aspectRatio: String(aspect) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} />
      </div>
      <div className="px-3 py-2">
        <div className="flex items-center gap-3 text-[#111]">
          <span aria-hidden className="text-[14px]">♡</span>
          <span aria-hidden className="text-[14px]">💬</span>
          <span aria-hidden className="text-[14px]">➤</span>
        </div>
        <p className="mt-1.5 text-[12px] leading-snug text-[#111]">
          <span className="mr-1.5 font-bold">{target.handle ? `@${target.handle}` : target.name}</span>
          {caption || "Your caption appears here."}
        </p>
        {overflow > 0 && (
          <p className="mt-1 text-[10px] font-semibold text-amber-600">
            {overflow} characters past Instagram&apos;s limit
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Facebook: landscape feed card with page header ───────────────── */

function FacebookPreview({
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
  const aspect =
    crop.key === "orig" ? 1.91 : crop.key === "9:16" ? CROP_ASPECT["9:16"] : CROP_ASPECT[crop.key as Exclude<CropState["key"], "orig">];
  return (
    <div className="mx-auto w-full max-w-[248px] overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white">
      <div className="flex items-center gap-2 px-3 pt-2.5 pb-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#e7f3ff] text-[13px] font-bold text-[#0a66c2]">
          {(target.name || "P").charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] font-bold text-[#111]">{target.name}</span>
          <span className="block text-[10px] text-[#65676b]">Just now · 🌐</span>
        </span>
      </div>
      {(caption || description) && (
        <p className="px-3 pb-2 text-[12px] leading-snug text-[#111]">
          {caption || description || "Your message appears here."}
        </p>
      )}
      <div className="w-full" style={{ aspectRatio: String(aspect) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} />
      </div>
      <div className="flex items-center justify-between border-t border-[#e4e6eb] px-3 py-1.5 text-[10px] font-semibold text-[#65676b]">
        <span>👍 ❤️ 🔥</span>
        <span>Share ›</span>
      </div>
    </div>
  );
}

/* ── WhatsApp: business message bubble inside a phone rail ────────── */

function WhatsAppPreview({
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
  const aspect = crop.key === "orig" ? 4 / 3 : CROP_ASPECT[crop.key as Exclude<CropState["key"], "orig">];
  return (
    <div className="mx-auto w-full max-w-[236px] overflow-hidden rounded-[14px] bg-[#eae6df] shadow-sm">
      <div className="flex items-center gap-2 bg-[#008069] px-3 py-2 text-white">
        <span className="text-[13px]">‹</span>
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/25 text-[10px] font-bold">
          {(target.name || "W").charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">{target.name}</span>
      </div>
      <div
        className="px-2 py-2"
        style={{
          backgroundColor: "#efeae2",
        }}
      >
        <div className="ml-auto w-[92%] overflow-hidden rounded-[8px] rounded-tr-none bg-[#d9fdd3] shadow-[0_1px_1px_rgba(0,0,0,0.12)]">
          <div style={{ aspectRatio: String(aspect) }}>
            <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} />
          </div>
          {(caption || description) && (
            <p className="px-2 pt-1.5 text-[11px] leading-snug text-[#111]">
              {caption || description || "Your update lands as a message."}
            </p>
          )}
          <p className="pb-1 pr-2 text-right text-[9px] text-[#667781]">
            10:24 <span className="text-[#53bdeb]">✓✓</span>
          </p>
        </div>
      </div>
    </div>
  );
}

/* ── Generic fallback for the main preview + later platforms ──────── */

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
  return (
    <div className="mx-auto w-full max-w-[248px] overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-white">
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--ui-sunken)] text-[11px] font-bold text-[var(--ui-ink)]">
          ✦
        </span>
        <span className="text-[12px] font-bold text-[#111]">{label}</span>
      </div>
      <div className="w-full" style={{ aspectRatio: String(crop.key === "orig" ? 4 / 3 : CROP_ASPECT[crop.key as Exclude<CropState["key"], "orig">]) }}>
        <CroppedMedia media={media} cropKey={crop.key} zoom={crop.zoom} offset={{ x: crop.x, y: crop.y }} />
      </div>
      {caption && <p className="px-3 py-2 text-[12px] leading-snug text-[#111]">{caption}</p>}
      {!caption && description && <p className="px-3 py-2 text-[12px] leading-snug text-[#111]">{description}</p>}
    </div>
  );
}

/* ── Registry ─────────────────────────────────────────────────────── */

export default function DestinationPreview({
  target,
  media,
  caption,
  description,
  crop,
}: {
  target: PublishTarget | null;
  media: MediaState;
  caption: string;
  description: string;
  crop: CropState;
}) {
  if (target) {
    switch (target.platform) {
      case "instagram":
        return <InstagramPreview target={target} media={media} caption={caption} crop={crop} />;
      case "facebook":
        return <FacebookPreview target={target} media={media} caption={caption} description={description} crop={crop} />;
      case "whatsapp":
        return <WhatsAppPreview target={target} media={media} caption={caption} description={description} crop={crop} />;
      default:
        return <GenericPreview label={target.name || "Destination"} media={media} caption={caption} description={description} crop={crop} />;
    }
  }
  return <GenericPreview label="How this post reads" media={media} caption={caption} description={description} crop={crop} />;
}

/* ── Shared bits ──────────────────────────────────────────────────── */

function PLATFORM_CAP_SAFE(p: string): number {
  const map: Record<string, number> = { instagram: 2200, facebook: 5000, whatsapp: 1024, x: 280 };
  return map[p] ?? 2200;
}

export function CropBadge({ crop }: { crop: CropState }) {
  if (crop.key === "orig") return null;
  return (
    <span className={`ml-auto shrink-0 rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${INK2}`}>
      {CROP_LABEL[crop.key]}
    </span>
  );
}
