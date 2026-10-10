"use client";

import type { WaProfile } from "@/lib/api-whatsapp-profile";

/** Real WhatsApp look: phone frame, WA header, doodle chat, business-card bubble + live sample thread.
 * Colors come from the hub's .wa-skin tokens, so the preview follows the app's light/dark theme. */
export default function PhonePreview({ draft, photoPreview, businessName }: { draft: Partial<WaProfile> & { displayName?: string }; photoPreview?: string | null; businessName?: string | null }) {
  const name = draft.displayName || businessName || "Your business";
  const about = draft.about || "Hey there! I am using WhatsApp.";
  return (
    <div className="md:sticky md:top-4">
      <p className="mb-2 text-center text-[11px] font-semibold uppercase tracking-widest text-[var(--wa-text-2)]">Live preview · as customers see it</p>
      <div className="mx-auto w-[300px] overflow-hidden rounded-[32px] bg-[var(--wa-frame)] p-2 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="overflow-hidden rounded-[24px] bg-[var(--wa-panel)]">
          {/* WA chat header */}
          <div className="flex items-center gap-2 bg-[var(--wa-deep)] px-3 py-2 text-[var(--wa-on-deep)]">
            <span className="text-[16px]">‹</span>
            <span className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-white/20 text-[12px] font-bold">
              <span className="absolute inset-0 flex items-center justify-center">{name[0] ?? "S"}</span>
              {photoPreview && <img src={photoPreview} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} className="relative h-full w-full object-cover" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold leading-tight">{name}</span>
              <span className="block text-[10px] text-[var(--wa-on-deep-muted)]">online · business account</span>
            </span>
            <span className="text-[13px] opacity-90">📹  📞</span>
          </div>
          {/* Doodle chat body — light/dark variants come from .wa-chat-canvas */}
          <div className="wa-chat-canvas space-y-2 px-3 py-3">
            {/* Business card bubble */}
            <div className="rounded-lg bg-[var(--wa-bubble-in)] p-3 shadow-[0_1px_1px_rgba(0,0,0,0.2)]">
              <div className="flex items-center gap-2.5">
                <span className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-[var(--wa-accent)]/15 text-[14px] font-bold text-[var(--wa-accent-deep)]">
                  <span className="absolute inset-0 flex items-center justify-center">{name[0] ?? "S"}</span>
                  {photoPreview && <img src={photoPreview} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} className="relative h-full w-full object-cover" />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-bold text-[var(--wa-text)]">{name}</span>
                  <span className="block truncate text-[11px] text-[var(--wa-text-2)]">{about}</span>
                </span>
              </div>
              {(draft.description || draft.address) && (
                <p className="mt-2 line-clamp-2 text-[11px] leading-snug text-[var(--wa-label)]">{draft.description || draft.address}</p>
              )}
              <div className="mt-2 border-t border-[var(--wa-border-soft)] pt-2 text-center text-[11px] font-semibold text-[var(--wa-accent)]">
                {(draft.websites ?? [])[0] ? (draft.websites ?? [])[0] : "View business profile ›"}
              </div>
            </div>
            {/* Sample thread — illustrative, not real messages */}
            <p className="pb-0.5 text-center text-[10px] uppercase tracking-widest text-[var(--wa-text-2)]">sample conversation</p>
            <div className="flex justify-start">
              <div className="max-w-[80%] rounded-lg rounded-tl-none bg-[var(--wa-bubble-in)] px-2.5 py-1.5 shadow-[0_1px_1px_rgba(0,0,0,0.2)]">
                <p className="text-[12px] text-[var(--wa-text)]">Hi! Are you open today?</p>
                <p className="mt-0.5 text-right text-[10px] text-[var(--wa-text-2)]">10:24</p>
              </div>
            </div>
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-lg rounded-tr-none bg-[var(--wa-bubble-out)] px-2.5 py-1.5 shadow-[0_1px_1px_rgba(0,0,0,0.2)]">
                <p className="text-[12px] text-[var(--wa-text)]">{about.length > 4 ? about : "Yes! Open till late 🕘"}</p>
                <p className="mt-0.5 text-right text-[10px] text-[var(--wa-text-2)]">10:25 <span className="text-[#53bdeb]">✓✓</span></p>
              </div>
            </div>
            <p className="pt-1 text-center text-[10px] text-[var(--wa-text-2)]">{draft.email ?? ""}</p>
          </div>
          {/* WA input bar */}
          <div className="flex items-center gap-2 bg-[var(--wa-panel-2)] px-2.5 py-1.5">
            <span className="flex-1 rounded-full bg-[var(--wa-input-bg)] px-3.5 py-1.5 text-[12px] text-[var(--wa-text-3)]">Message</span>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--wa-accent)] text-[14px] text-white">➤</span>
          </div>
        </div>
      </div>
    </div>
  );
}
