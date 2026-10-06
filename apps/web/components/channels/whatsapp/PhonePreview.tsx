"use client";

import type { WaProfile } from "@/lib/api-whatsapp-profile";

/** Sticky live mock of the WhatsApp business card. Updates as you type. */
export default function PhonePreview({ draft, photoPreview }: { draft: Partial<WaProfile> & { displayName?: string }; photoPreview?: string | null }) {
  return (
    <div className="lg:sticky lg:top-4">
      <div className="overflow-hidden rounded-[24px] bg-[#0B141A] p-3 shadow-lg">
        <div className="rounded-[18px] bg-[#EFEAE2] p-4">
          <p className="text-center text-[10px] font-semibold uppercase tracking-widest text-black/40">Live preview · business card</p>
          <div className="mt-3 rounded-2xl bg-white p-4 shadow-sm">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-[#25D366] text-lg font-bold text-white">
                {photoPreview ? <img src={photoPreview} alt="" className="h-full w-full object-cover" /> : (draft.displayName?.[0] ?? "S")}
              </div>
              <div className="min-w-0">
                <p className="truncate text-[15px] font-bold text-[#111B21]">
                  {draft.displayName || "Your business"} <span className="text-[#25D366]" title="verified">✓</span>
                </p>
                <p className="truncate text-[12px] text-black/50">{draft.about || "About line — 139 characters"}</p>
              </div>
            </div>
            {(draft.description || draft.address) && (
              <p className="mt-3 line-clamp-3 text-[13px] leading-relaxed text-black/70">{draft.description || draft.address}</p>
            )}
            <div className="mt-3 flex gap-2">
              <span className="min-h-11 flex-1 rounded-xl bg-[#25D366] px-3 py-2 text-center text-[13px] font-bold text-white">Message</span>
              {(draft.websites?.length ?? 0) > 0 && (
                <span className="min-h-11 flex-1 truncate rounded-xl border border-black/10 px-3 py-2 text-center text-[13px] font-semibold text-black/60">
                  {(draft.websites ?? [])[0]}
                </span>
              )}
            </div>
          </div>
          <p className="mt-2 text-center text-[11px] text-black/40">{draft.email ?? ""}</p>
        </div>
      </div>
    </div>
  );
}
