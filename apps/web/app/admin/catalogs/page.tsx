"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";

interface Dialect {
  code: string;
  dialect_en: string;
  dialect_ar: string;
  examples: string[];
}
interface Tone {
  code: string;
  label: string;
  description: string;
}

export default function AdminCatalogsPage() {
  const [dialects, setDialects] = useState<Dialect[]>([]);
  const [tones, setTones] = useState<Tone[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  // Dialect form
  const [dForm, setDForm] = useState({ code: "", dialect_en: "", dialect_ar: "", examples: "" });
  // Tone form
  const [tForm, setTForm] = useState({ code: "", label: "", description: "" });
  // Inline tone edit
  const [editingTone, setEditingTone] = useState<string | null>(null);
  const [toneEdit, setToneEdit] = useState({ label: "", description: "" });

  const load = useCallback(async () => {
    try {
      const [d, t] = await Promise.all([
        adminFetch<Dialect[]>("/api/v1/admin/dialects"),
        adminFetch<Tone[]>("/api/v1/admin/tones"),
      ]);
      setDialects(d ?? []);
      setTones(t ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load catalogs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function addDialect() {
    if (!dForm.code.trim() || !dForm.dialect_en.trim() || !dForm.dialect_ar.trim()) return;
    setBusy("dialect:add");
    try {
      await adminFetch("/api/v1/admin/dialects", {
        method: "POST",
        body: JSON.stringify({
          code: dForm.code.trim(),
          dialect_en: dForm.dialect_en.trim(),
          dialect_ar: dForm.dialect_ar.trim(),
          examples: dForm.examples.split(",").map((x) => x.trim()).filter(Boolean),
        }),
      });
      setDForm({ code: "", dialect_en: "", dialect_ar: "", examples: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add dialect.");
    } finally {
      setBusy(null);
    }
  }

  async function deleteDialect(code: string) {
    if (!confirm(`Delete dialect "${code}"? Channels using it fall back to auto.`)) return;
    setBusy(`dialect:${code}`);
    try {
      await adminFetch(`/api/v1/admin/dialects/${encodeURIComponent(code)}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete dialect.");
    } finally {
      setBusy(null);
    }
  }

  async function addTone() {
    if (!tForm.code.trim() || !tForm.label.trim()) return;
    setBusy("tone:add");
    try {
      await adminFetch("/api/v1/admin/tones", {
        method: "POST",
        body: JSON.stringify({ code: tForm.code.trim(), label: tForm.label.trim(), description: tForm.description.trim() }),
      });
      setTForm({ code: "", label: "", description: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add tone.");
    } finally {
      setBusy(null);
    }
  }

  async function saveTone(code: string) {
    setBusy(`tone:${code}`);
    try {
      await adminFetch(`/api/v1/admin/tones/${encodeURIComponent(code)}`, {
        method: "PUT",
        body: JSON.stringify({ label: toneEdit.label, description: toneEdit.description }),
      });
      setEditingTone(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update tone.");
    } finally {
      setBusy(null);
    }
  }

  async function deleteTone(code: string) {
    if (!confirm(`Delete tone "${code}"? Channels keep working with their stored value.`)) return;
    setBusy(`tone:${code}`);
    try {
      await adminFetch(`/api/v1/admin/tones/${encodeURIComponent(code)}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete tone.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  return (
    <div className="space-y-5">
      {error && <p className="rounded-xl bg-coral/10 px-4 py-3 text-[12px] font-medium text-coral">{error}</p>}
      <p className="text-[12px] text-ink/50">Reply engine catalogs — what the AI can sound like (tones) and which Arabic dialect it speaks (dialects). Changes apply to every tenant instantly.</p>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Dialects */}
        <section className="rounded-2xl border border-white bg-white/80 p-4">
          <h2 className="text-[14px] font-bold text-ink">Dialects ({dialects.length})</h2>
          <div className="mt-3 space-y-1.5">
            {dialects.map((d) => (
              <div key={d.code} className="flex items-center gap-2 rounded-lg bg-ink/[0.02] px-3 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-semibold text-ink">
                    {d.code === "auto" ? d.dialect_en : `${d.dialect_en} · ${d.dialect_ar}`}
                  </span>
                  <span className="block text-[10px] text-ink/40">{d.code}{d.examples.length ? ` · ${d.examples.length} examples` : ""}</span>
                </span>
                {d.code !== "auto" && (
                  <button onClick={() => void deleteDialect(d.code)} disabled={busy !== null} className="text-[11px] font-semibold text-coral hover:underline disabled:opacity-40">
                    Delete
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-2 rounded-xl border border-deep-violet/20 bg-deep-violet/[0.03] p-3">
            <p className="text-[11px] font-bold uppercase tracking-wide text-deep-violet">Add dialect</p>
            <div className="grid gap-2 sm:grid-cols-3">
              <input value={dForm.code} onChange={(e) => setDForm({ ...dForm, code: e.target.value })} placeholder="code (e.g. hijazi)" className="input-field" />
              <input value={dForm.dialect_en} onChange={(e) => setDForm({ ...dForm, dialect_en: e.target.value })} placeholder="Name (English)" className="input-field" />
              <input value={dForm.dialect_ar} onChange={(e) => setDForm({ ...dForm, dialect_ar: e.target.value })} placeholder="Name (Arabic)" className="input-field" dir="rtl" />
            </div>
            <input value={dForm.examples} onChange={(e) => setDForm({ ...dForm, examples: e.target.value })} placeholder="Example phrases, comma separated" className="input-field w-full" />
            <button onClick={() => void addDialect()} disabled={busy !== null || !dForm.code.trim() || !dForm.dialect_en.trim() || !dForm.dialect_ar.trim()} className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-40">
              {busy === "dialect:add" ? "Adding…" : "Add dialect"}
            </button>
          </div>
        </section>

        {/* Tones */}
        <section className="rounded-2xl border border-white bg-white/80 p-4">
          <h2 className="text-[14px] font-bold text-ink">Tones ({tones.length})</h2>
          <div className="mt-3 space-y-1.5">
            {tones.map((t) => (
              <div key={t.code} className="rounded-lg bg-ink/[0.02] px-3 py-2">
                {editingTone === t.code ? (
                  <div className="space-y-2">
                    <input value={toneEdit.label} onChange={(e) => setToneEdit({ ...toneEdit, label: e.target.value })} placeholder="Label" className="input-field" />
                    <input value={toneEdit.description} onChange={(e) => setToneEdit({ ...toneEdit, description: e.target.value })} placeholder="Description" className="input-field" />
                    <div className="flex gap-2">
                      <button onClick={() => void saveTone(t.code)} disabled={busy !== null} className="rounded-lg bg-deep-violet px-3 py-1 text-[11px] font-bold text-white disabled:opacity-40">Save</button>
                      <button onClick={() => setEditingTone(null)} className="rounded-lg border border-ink/10 px-3 py-1 text-[11px] font-bold text-ink/50">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] font-semibold text-ink">{t.label} <span className="font-normal text-ink/40">({t.code})</span></span>
                      {t.description && <span className="block truncate text-[11px] text-ink/45">{t.description}</span>}
                    </span>
                    <button
                      onClick={() => { setEditingTone(t.code); setToneEdit({ label: t.label, description: t.description }); }}
                      disabled={busy !== null}
                      className="text-[11px] font-semibold text-deep-violet hover:underline disabled:opacity-40"
                    >
                      Edit
                    </button>
                    <button onClick={() => void deleteTone(t.code)} disabled={busy !== null} className="text-[11px] font-semibold text-coral hover:underline disabled:opacity-40">
                      Delete
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-2 rounded-xl border border-deep-violet/20 bg-deep-violet/[0.03] p-3">
            <p className="text-[11px] font-bold uppercase tracking-wide text-deep-violet">Add tone</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <input value={tForm.code} onChange={(e) => setTForm({ ...tForm, code: e.target.value })} placeholder="code (e.g. bold)" className="input-field" />
              <input value={tForm.label} onChange={(e) => setTForm({ ...tForm, label: e.target.value })} placeholder="Label" className="input-field" />
            </div>
            <input value={tForm.description} onChange={(e) => setTForm({ ...tForm, description: e.target.value })} placeholder="Description" className="input-field w-full" />
            <button onClick={() => void addTone()} disabled={busy !== null || !tForm.code.trim() || !tForm.label.trim()} className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-40">
              {busy === "tone:add" ? "Adding…" : "Add tone"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
