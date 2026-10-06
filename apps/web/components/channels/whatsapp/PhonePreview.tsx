"use client";

import type { WaProfile } from "@/lib/api-whatsapp-profile";

const DOODLE = `background-color:#efeae2;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='none' stroke='%23000' stroke-opacity='0.06' stroke-width='1.4'%3E%3Ccircle cx='18' cy='22' r='6'/%3E%3Cpath d='M45 12h14M52 5v14'/%3E%3Crect x='78' y='10' width='12' height='12' rx='2'/%3E%3Cpath d='M10 58q6-8 12 0t12 0'/%3E%3Cpath d='M78 56l4 8 8 4-8 4-4 8-4-8-8-4 8-4z'/%3E%3Ccircle cx='60' cy='100' r='7'/%3E%3C/g%3E%3C/svg%3E")`;

/** Real WhatsApp look: phone frame, WA header, doodle chat, business-card bubble + live sample thread. */
export default function PhonePreview({ draft, photoPreview }: { draft: Partial<WaProfile> & { displayName?: string }; photoPreview?: string | null }) {
  const name = draft.displayName || "Your business";
  const about = draft.about || "Hey there! I am using WhatsApp.";
  return (
    <div className="lg:sticky lg:top-4">
      <p className="mb-2 text-center text-[11px] font-semibold uppercase tracking-widest text-[#667781]">Live preview · as customers see it</p>
      <div className="mx-auto w-[300px] overflow-hidden rounded-[32px] bg-[#0b141a] p-2 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="overflow-hidden rounded-[24px] bg-white">
          {/* WA chat header */}
          <div className="flex items-center gap-2 bg-[#075e54] px-3 py-2 text-white">
            <span className="text-[16px]">‹</span>
            <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-white/20 text-[12px] font-bold">
              {photoPreview ? <img src={photoPreview} alt="" className="h-full w-full object-cover" /> : (name[0] ?? "S")}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold leading-tight">{name} <span className="text-[#53bdeb]">✓</span></span>
              <span className="block text-[10px] text-white/80">online · business account</span>
            </span>
            <span className="text-[13px] text-white/90">📹  📞</span>
          </div>
          {/* Doodle chat body */}
          <div className="space-y-2 px-3 py-3" style={{ background: "#efeae2", backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='none' stroke='%23000' stroke-opacity='0.06' stroke-width='1.4'%3E%3Ccircle cx='18' cy='22' r='6'/%3E%3Cpath d='M45 12h14M52 5v14'/%3E%3Crect x='78' y='10' width='12' height='12' rx='2'/%3E%3Cpath d='M10 58q6-8 12 0t12 0'/%3E%3Cpath d='M78 56l4 8 8 4-8 4-4 8-4-8-8-4 8-4z'/%3E%3Ccircle cx='60' cy='100' r='7'/%3E%3C/g%3E%3C/svg%3E")` }}>
            {/* Business card bubble */}
            <div className="rounded-lg bg-white p-3 shadow-[0_1px_1px_rgba(0,0,0,0.2)]">
              <div className="flex items-center gap-2.5">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-[#00a884]/15 text-[14px] font-bold text-[#008069]">
                  {photoPreview ? <img src={photoPreview} alt="" className="h-full w-full object-cover" /> : (name[0] ?? "S")}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-bold text-[#111b21]">{name} <span className="text-[#00a884]">✓</span></span>
                  <span className="block truncate text-[11px] text-[#667781]">{about}</span>
                </span>
              </div>
              {(draft.description || draft.address) && (
                <p className="mt-2 line-clamp-2 text-[11px] leading-snug text-[#3b4a54]">{draft.description || draft.address}</p>
              )}
              <div className="mt-2 border-t border-black/[0.06] pt-2 text-center text-[11px] font-semibold text-[#00a884]">
                {(draft.websites ?? [])[0] ? (draft.websites ?? [])[0] : "View business profile ›"}
              </div>
            </div>
            {/* Sample thread */}
            <div className="flex justify-start">
              <div className="max-w-[80%] rounded-lg rounded-tl-none bg-white px-2.5 py-1.5 shadow-[0_1px_1px_rgba(0,0,0,0.2)]">
                <p className="text-[12px] text-[#111b21]">Hi! Are you open today?</p>
                <p className="mt-0.5 text-right text-[10px] text-[#667781]">10:24</p>
              </div>
            </div>
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-lg rounded-tr-none bg-[#d9fdd3] px-2.5 py-1.5 shadow-[0_1px_1px_rgba(0,0,0,0.2)]">
                <p className="text-[12px] text-[#111b21]">{about.length > 4 ? about : "Yes! Open till late 🕘"}</p>
                <p className="mt-0.5 text-right text-[10px] text-[#667781]">10:25 <span className="text-[#53bdeb]">✓✓</span></p>
              </div>
            </div>
            <p className="pt-1 text-center text-[10px] text-[#667781]">{draft.email ?? ""}</p>
          </div>
          {/* WA input bar */}
          <div className="flex items-center gap-2 bg-[#f0f2f5] px-2.5 py-1.5">
            <span className="flex-1 rounded-full bg-white px-3.5 py-1.5 text-[12px] text-[#8696a0]">Message</span>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#00a884] text-[14px] text-white">➤</span>
          </div>
        </div>
      </div>
      <span className="hidden">{DOODLE}</span>
    </div>
  );
}
