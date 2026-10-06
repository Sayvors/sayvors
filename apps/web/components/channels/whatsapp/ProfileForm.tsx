"use client";

import { useEffect, useState } from "react";
import {
  fetchWaProfile, saveWaProfile, completeness, normalizeUrl, WA_VERTICALS, type WaProfile,
} from "@/lib/api-whatsapp-profile";
import PhonePreview from "./PhonePreview";

type Draft = Partial<WaProfile> & { displayName?: string };

export default function ProfileForm({ phoneId }: { phoneId: string }) {
  const [profile, setProfile] = useState<WaProfile | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("loading");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    setStatus("loading");
    fetchWaProfile(phoneId)
      .then((p) => {
        if (dead) return;
        setProfile(p);
        setDraft({ ...p });
        try {
          const raw = sessionStorage.getItem(`wa-draft-${phoneId}`);
          if (raw) setDraft((d) => ({ ...d, ...(JSON.parse(raw) as Draft) }));
        } catch { /* no draft */ }
        setStatus("idle");
      })
      .catch(() => {
        if (!dead) {
          setStatus("error");
          setMsg("Couldn't load the profile. Check your connection.");
        }
      });
    return () => {
      dead = true;
    };
  }, [phoneId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(`wa-draft-${phoneId}`, JSON.stringify(draft));
    } catch { /* storage off */ }
  }, [draft, phoneId]);

  const set = (k: keyof Draft, v: string | string[]) => {
    setDraft((d) => ({ ...d, [k]: v }));
    if (errors[k as string]) {
      setErrors((e) => {
        const n = { ...e };
        delete n[k as string];
        return n;
      });
    }
  };

  const validate = (d: Draft): Record<string, string> => {
    const e: Record<string, string> = {};
    if (d.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.email)) e.email = "Emails need an @ — check for a typo.";
    if ((d.about ?? "").length > 139) e.about = `Keep About under 139 characters (${(d.about ?? "").length} now).`;
    if ((d.description ?? "").length > 512) e.description = "Keep Description under 512 characters.";
    return e;
  };

  const save = async () => {
    const v = validate(draft);
    setErrors(v);
    if (Object.keys(v).length) {
      setMsg("Fix the highlighted fields, then save again.");
      return;
    }
    setStatus("saving");
    setMsg(null);
    try {
      const patch: Partial<WaProfile> = {
        about: draft.about ?? undefined,
        address: draft.address ?? undefined,
        description: draft.description ?? undefined,
        email: draft.email ?? undefined,
        vertical: draft.vertical ?? undefined,
        websites: draft.websites?.map(normalizeUrl),
      };
      const updated = await saveWaProfile(phoneId, patch);
      setProfile(updated);
      try {
        sessionStorage.removeItem(`wa-draft-${phoneId}`);
      } catch { /* noop */ }
      setStatus("saved");
      setMsg("Saved — live on WhatsApp now.");
      setTimeout(() => setStatus("idle"), 2500);
    } catch (e) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message.slice(0, 200) : "Couldn't save. Your changes are kept — try again.");
    }
  };

  const score = completeness({ ...(profile ?? { about: null, address: null, description: null, email: null, websites: [], vertical: null, profile_picture_url: null }), ...draft } as WaProfile);
  const inputCls = "min-h-11 w-full rounded-lg border border-black/15 bg-white px-3.5 py-2.5 text-[14px] text-[#111b21] outline-none transition placeholder:text-[#8696a0] focus:border-[#00a884] focus:ring-2 focus:ring-[#00a884]/25";

  if (status === "loading") {
    return (
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="animate-pulse space-y-3"><div className="h-12 rounded-lg bg-white shadow" /><div className="h-24 rounded-lg bg-white shadow" /><div className="h-12 rounded-lg bg-white shadow" /></div>
        <div className="h-80 animate-pulse rounded-[32px] bg-white shadow" />
      </div>
    );
  }

  return (
    <div style={{ fontFamily: '"Segoe UI",Helvetica Neue,Helvetica,Arial,sans-serif' }}>
      <div className="mb-4 flex items-center gap-3 rounded-lg bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[#00a884]/15 text-[15px] font-bold text-[#008069]" aria-label={`Profile ${score}% complete`}>{score}%</div>
        <div className="min-w-0 flex-1">
          <div className="h-2 overflow-hidden rounded-full bg-black/[0.08]"><div className="h-full rounded-full bg-[#00a884] transition-all" style={{ width: `${score}%` }} /></div>
          <p className="mt-1 text-[12px] text-[#667781]">{score >= 90 ? "All caught up — looking sharp." : "Add a photo, About and a website to reach 90%+."}</p>
        </div>
        <button onClick={save} disabled={status === "saving"} className="min-h-11 shrink-0 rounded-full bg-[#00a884] px-6 py-2.5 text-[13px] font-semibold text-white shadow transition hover:bg-[#008069] active:scale-[0.98] disabled:opacity-60">
          {status === "saving" ? "Saving…" : "Save"}
        </button>
      </div>

      {msg && (
        <div role="status" className={`mx-auto mb-3 flex max-w-md items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] shadow ${status === "error" ? "bg-[#fff3cd] text-[#664d03]" : "bg-[#d1f4cc] text-[#0f5132]"}`}>{msg}</div>
      )}

      {!profile && status === "error" && (
        <div className="rounded-lg bg-white p-6 text-center shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
          <p className="font-semibold text-[#111b21]">No profile yet</p>
          <p className="mt-1 text-[13px] text-[#667781]">Fill the form — the preview shows exactly what customers see.</p>
        </div>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4 rounded-lg bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)] sm:p-5">
          <div>
            <label htmlFor="wa-about" className="mb-1.5 block text-[13px] font-semibold">About {(draft.about ?? "").length}/139</label>
            <input id="wa-about" value={draft.about ?? ""} onChange={(e) => set("about", e.target.value)} onBlur={() => setTouched((t) => ({ ...t, about: true }))} placeholder="Fresh coffee downtown, open till late" className={inputCls} maxLength={200} />
            {errors.about && <p className="mt-1 text-[12px] text-red-600">{errors.about}</p>}
          </div>
          <div>
            <label htmlFor="wa-desc" className="mb-1.5 block text-[13px] font-semibold">Description (optional)</label>
            <textarea id="wa-desc" value={draft.description ?? ""} onChange={(e) => set("description", e.target.value)} rows={3} placeholder="What you sell, hours, parking…" className={inputCls} maxLength={600} />
            {errors.description && <p className="mt-1 text-[12px] text-red-600">{errors.description}</p>}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="wa-email" className="mb-1.5 block text-[13px] font-semibold">Email (optional)</label>
              <input id="wa-email" type="email" inputMode="email" autoComplete="email" value={draft.email ?? ""} onChange={(e) => set("email", e.target.value)} onBlur={() => setTouched((t) => ({ ...t, email: true }))} placeholder="hello@shop.com" className={inputCls} />
              {errors.email && <p className="mt-1 text-[12px] text-red-600">{errors.email}</p>}
            </div>
            <div>
              <label htmlFor="wa-vertical" className="mb-1.5 block text-[13px] font-semibold">Category</label>
              <select id="wa-vertical" value={draft.vertical ?? ""} onChange={(e) => set("vertical", e.target.value)} className={inputCls}>
                <option value="">Pick one…</option>
                {WA_VERTICALS.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="wa-addr" className="mb-1.5 block text-[13px] font-semibold">Address (optional)</label>
            <input id="wa-addr" value={draft.address ?? ""} onChange={(e) => set("address", e.target.value)} autoComplete="street-address" placeholder="12 Main St, City" className={inputCls} />
          </div>
          <div>
            <label htmlFor="wa-web" className="mb-1.5 block text-[13px] font-semibold">Website (optional)</label>
            <input id="wa-web" value={(draft.websites ?? [])[0] ?? ""} onChange={(e) => set("websites", [e.target.value])} inputMode="url" placeholder="shop.com" className={inputCls} />
          </div>
        </div>
        <PhonePreview draft={draft} />
      </div>
    </div>
  );
}
