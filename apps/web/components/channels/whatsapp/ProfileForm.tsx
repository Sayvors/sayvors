"use client";

import { useEffect, useRef, useState } from "react";
import {
  fetchWaProfile, saveWaProfile, uploadWaPhoto, completeness, normalizeUrl, WA_VERTICALS, type WaProfile,
} from "@/lib/api-whatsapp-profile";
import { useI18n } from "@/lib/i18n/I18nProvider";
import PhonePreview from "./PhonePreview";

type Draft = Partial<WaProfile> & { displayName?: string };

/** Localized "x ago" for sync labels (keeps the shared English lib untouched). */
function agoLabel(iso: string | null | undefined, t: {
  now: string;
  mins: string;
  hours: string;
  days: string;
}): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return t.now;
  if (mins < 60) return t.mins.replace("{n}", String(mins));
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t.hours.replace("{n}", String(hours));
  return t.days.replace("{n}", String(Math.floor(hours / 24)));
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

export default function ProfileForm({ phoneId, businessName }: { phoneId: string; businessName?: string | null }) {
  const { t } = useI18n();
  const p = t.dashboard.whatsapp.profile;
  const [profile, setProfile] = useState<WaProfile | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("loading");
  const [msg, setMsg] = useState<string | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  // Only user edits are worth persisting — writing the fetched profile out on
  // every load would let a previously-empty response poison later loads.
  const dirtyRef = useRef(false);

  useEffect(() => {
    let dead = false;
    fetchWaProfile(phoneId)
      .then((p) => {
        if (dead) return;
        setProfile(p);
        setDraft({ ...p });
        try {
          const raw = sessionStorage.getItem(`wa-draft-${phoneId}`);
          if (raw) {
            // Restore edits, but never let stored nulls/empties blank out
            // fields the server now has data for.
            const stored = JSON.parse(raw) as Draft;
            const cleaned: Draft = {};
            for (const [k, v] of Object.entries(stored)) {
              if (v === null || v === undefined || v === "") continue;
              if (Array.isArray(v) && v.length === 0) continue;
              (cleaned as Record<string, unknown>)[k] = v;
            }
            setDraft((d) => ({ ...d, ...cleaned }));
            dirtyRef.current = Object.keys(cleaned).length > 0;
          }
        } catch { /* no draft */ }
        setStatus("idle");
      })
      .catch(() => {
        if (!dead) {
          setStatus("error");
          setMsg(p.loadFail);
        }
      });
    return () => {
      dead = true;
    };
  }, [phoneId]);

  useEffect(() => {
    if (!dirtyRef.current) return;
    try {
      sessionStorage.setItem(`wa-draft-${phoneId}`, JSON.stringify(draft));
    } catch { /* storage off */ }
  }, [draft, phoneId]);

  const set = (k: keyof Draft, v: string | string[]) => {
    dirtyRef.current = true;
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
    if (d.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.email)) e.email = p.emailFix;
    if ((d.about ?? "").length > 139) e.about = fill(p.aboutLen, { count: (d.about ?? "").length });
    if ((d.description ?? "").length > 512) e.description = p.descLen;
    return e;
  };

  const save = async () => {
    const v = validate(draft);
    setErrors(v);
    if (Object.keys(v).length) {
      setMsg(p.fixFields);
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
      setMsg(p.savedLive);
      setTimeout(() => setStatus("idle"), 2500);
    } catch (e) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message.slice(0, 200) : p.saveFail);
    }
  };

  const onPhoto = async (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setMsg(p.photoType);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setMsg(p.photoSize);
      return;
    }
    setPhotoBusy(true);
    setMsg(null);
    try {
      const updated = await uploadWaPhoto(phoneId, file);
      setProfile(updated);
      setPhotoPreview(URL.createObjectURL(file));
      setMsg(p.photoOk);
      setTimeout(() => setStatus("idle"), 2500);
    } catch (e) {
      setMsg(e instanceof Error ? e.message.slice(0, 200) : p.uploadFail);
    } finally {
      setPhotoBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const score = completeness({ ...(profile ?? { about: null, address: null, description: null, email: null, websites: [], vertical: null, profile_picture_url: null }), ...draft } as WaProfile);
  const inputCls = "min-h-11 w-full rounded-lg border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3.5 py-2.5 text-[14px] text-[var(--wa-text)] outline-none transition placeholder:text-[var(--wa-text-3)] focus:border-[var(--wa-accent)] focus:ring-2 focus:ring-[var(--wa-accent)]/25";
  const labelCls = "mb-1.5 block text-[13px] font-medium text-[var(--wa-label)]";

  if (status === "loading") {
    return (
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="animate-pulse space-y-3"><div className="h-12 rounded-lg bg-[var(--wa-panel)] shadow" /><div className="h-24 rounded-lg bg-[var(--wa-panel)] shadow" /><div className="h-12 rounded-lg bg-[var(--wa-panel)] shadow" /></div>
        <div className="h-80 animate-pulse rounded-[32px] bg-[var(--wa-panel)] shadow" />
      </div>
    );
  }

  return (
    <div style={{ fontFamily: '"Segoe UI",Helvetica Neue,Helvetica,Arial,sans-serif' }}>
      <div className="mb-4 flex items-center gap-3 rounded-lg bg-[var(--wa-panel)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--wa-accent)]/15 text-[15px] font-bold text-[var(--wa-accent-deep)]" aria-label={fill(p.completeAria, { score })}>{score}%</div>
        <div className="min-w-0 flex-1">
          <div className="h-2 overflow-hidden rounded-full bg-[var(--wa-track)]"><div className="h-full rounded-full bg-[var(--wa-accent)] transition-all" style={{ width: `${score}%` }} /></div>
          <p className="mt-1 text-[12px] text-[var(--wa-text-2)]">
            {score >= 90 ? p.sharp : p.progressHint}
            {profile?.synced_at && !profile?.stale && fill(p.syncedFrom, { time: agoLabel(profile.synced_at, t.dashboard.inbox.time) })}
          </p>
        </div>
        <button onClick={save} disabled={status === "saving"} className="min-h-11 shrink-0 rounded-full bg-[var(--wa-accent)] px-6 py-2.5 text-[13px] font-semibold text-white shadow transition hover:bg-[var(--wa-accent-deep)] active:scale-[0.98] disabled:opacity-60">
          {status === "saving" ? p.saving : p.save}
        </button>
      </div>

      {msg && (
        <div role="status" className={`mx-auto mb-3 flex max-w-md items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] shadow ${status === "error" ? "bg-[var(--wa-warn-bg)] text-[var(--wa-warn-text)]" : "bg-[var(--wa-ok-bg)] text-[var(--wa-ok-text)]"}`}>{msg}</div>
      )}

      {profile?.stale && (
        <div role="status" className="mb-3 flex max-w-md items-center gap-2 rounded-lg bg-[var(--wa-warn-bg)] px-4 py-2.5 text-[13px] text-[var(--wa-warn-text)] shadow">
          {fill(p.stale, { time: agoLabel(profile.synced_at, t.dashboard.inbox.time) || p.lastSync })}
        </div>
      )}

      {!profile && status === "error" && (
        <div className="rounded-lg bg-[var(--wa-panel)] p-6 text-center shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
          <p className="font-semibold text-[var(--wa-text)]">{p.noProfile}</p>
          <p className="mt-1 text-[13px] text-[var(--wa-text-2)]">{p.fillForm}</p>
        </div>
      )}

      <div className="grid items-start gap-4 md:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4 rounded-lg bg-[var(--wa-panel)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)] sm:p-5">
          <div className="flex items-center gap-4">
            <div className="relative">
              <div className="relative flex h-20 w-20 items-center justify-center overflow-hidden rounded-full bg-[var(--wa-track)] text-2xl font-bold text-[var(--wa-text-2)]">
                <span className="absolute inset-0 flex items-center justify-center">{businessName?.[0] ?? "B"}</span>
                {(photoPreview || profile?.profile_picture_url) && (
                  // eslint-disable-next-line @next/next/no-img-element -- remote/blob preview, DOM onError fallback
                  <img
                    src={photoPreview || profile?.profile_picture_url || ""}
                    alt="Profile"
                    onError={(e) => { e.currentTarget.style.display = "none"; }}
                    className="relative h-full w-full object-cover"
                  />
                )}
              </div>
              {photoBusy && (
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 text-white">
                  <span className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold text-[var(--wa-text)]">{p.photoTitle}</p>
              <p className="mt-0.5 text-[12px] text-[var(--wa-text-2)]">{p.photoSub}</p>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={photoBusy}
                  className="min-h-11 rounded-full border border-[var(--wa-accent)] px-4 text-[12px] font-semibold text-[var(--wa-accent-deep)] transition hover:bg-[var(--wa-accent)]/10 disabled:opacity-50"
                >
                  {photoBusy ? p.uploading : p.uploadPhoto}
                </button>
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => void onPhoto(e.target.files?.[0])} />
              </div>
            </div>
          </div>
          <div>
            <label htmlFor="wa-about" className={labelCls}>{fill(p.about, { count: (draft.about ?? "").length })}</label>
            <input id="wa-about" value={draft.about ?? ""} onChange={(e) => set("about", e.target.value)} placeholder={p.aboutPh} className={inputCls} maxLength={200} />
            {errors.about && <p className="mt-1 text-[12px] text-[var(--wa-danger)]">{errors.about}</p>}
          </div>
          <div>
            <label htmlFor="wa-desc" className={labelCls}>{p.description}</label>
            <textarea id="wa-desc" value={draft.description ?? ""} onChange={(e) => set("description", e.target.value)} rows={3} placeholder={p.descriptionPh} className={inputCls} maxLength={600} />
            {errors.description && <p className="mt-1 text-[12px] text-[var(--wa-danger)]">{errors.description}</p>}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="wa-email" className={labelCls}>{p.email}</label>
              <input id="wa-email" type="email" inputMode="email" autoComplete="email" value={draft.email ?? ""} onChange={(e) => set("email", e.target.value)} placeholder="hello@shop.com" className={inputCls} />
              {errors.email && <p className="mt-1 text-[12px] text-[var(--wa-danger)]">{errors.email}</p>}
            </div>
            <div>
              <label htmlFor="wa-vertical" className={labelCls}>{p.category}</label>
              <select id="wa-vertical" value={draft.vertical ?? ""} onChange={(e) => set("vertical", e.target.value)} className={inputCls}>
                <option value="">{p.pickOne}</option>
                {WA_VERTICALS.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
                {draft.vertical && !WA_VERTICALS.some((v) => v.value === draft.vertical) && (
                  <option value={draft.vertical}>{draft.vertical}</option>
                )}
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="wa-addr" className={labelCls}>{p.address}</label>
            <input id="wa-addr" value={draft.address ?? ""} onChange={(e) => set("address", e.target.value)} autoComplete="street-address" placeholder="12 Main St, City" className={inputCls} />
          </div>
          <div>
            <label htmlFor="wa-web" className={labelCls}>{p.website}</label>
            <input id="wa-web" value={(draft.websites ?? [])[0] ?? ""} onChange={(e) => set("websites", [e.target.value])} inputMode="url" placeholder="shop.com" className={inputCls} />
          </div>
        </div>
        {/* Preview first on mobile (stacked), beside the form from md up */}
        <div className="order-first md:order-none">
          <PhonePreview draft={draft} photoPreview={photoPreview || profile?.profile_picture_url || null} businessName={businessName} />
        </div>
      </div>
    </div>
  );
}
