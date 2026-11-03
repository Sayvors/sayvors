"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface Persona {
  id: string;
  name: string;
  gender: "female" | "male" | "neutral";
  description: string | null;
  instructions: string | null;
  is_active: boolean;
  sort_order: number;
}

interface Draft {
  name: string;
  gender: "female" | "male" | "neutral";
  description: string;
  instructions: string;
  sort_order: number;
}

const INPUT =
  "w-full rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] text-ink outline-none transition focus:border-deep-violet";

function draftOf(p: Persona): Draft {
  return {
    name: p.name,
    gender: p.gender,
    description: p.description ?? "",
    instructions: p.instructions ?? "",
    sort_order: p.sort_order,
  };
}

function emptyDraft(): Draft {
  return { name: "", gender: "female", description: "", instructions: "", sort_order: 100 };
}

export default function AdminPersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [fresh, setFresh] = useState<Draft>(emptyDraft());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = useCallback((list: Persona[]) => {
    setPersonas(list);
    setDrafts(Object.fromEntries(list.map((p) => [p.id, draftOf(p)])));
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    adminFetch<{ personas: Persona[] }>("/api/v1/admin/personas")
      .then((data) => apply(data.personas))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load personas."))
      .finally(() => setLoading(false));
  }, [apply]);

  useEffect(() => {
    load();
  }, [load]);

  const setDraft = (id: string, patch: Partial<Draft>) => {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  };

  const save = async (p: Persona) => {
    const d = drafts[p.id];
    if (!d) return;
    setBusy(p.id);
    setError(null);
    setNotice(null);
    try {
      await adminFetch(`/api/v1/admin/personas/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: d.name,
          gender: d.gender,
          description: d.description || null,
          instructions: d.instructions || null,
          sort_order: Number(d.sort_order) || 0,
        }),
      });
      setNotice(`${d.name} saved.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  };

  const activate = async (p: Persona) => {
    setBusy(p.id);
    setError(null);
    setNotice(null);
    try {
      await adminFetch(`/api/v1/admin/personas/${p.id}/activate`, { method: "POST" });
      setNotice(`${p.name} is now the active persona for every tenant.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not activate the persona.");
    } finally {
      setBusy(null);
    }
  };

  const remove = async (p: Persona) => {
    if (!confirm(`Delete persona "${p.name}"? This cannot be undone.`)) return;
    setBusy(p.id);
    setError(null);
    setNotice(null);
    try {
      await adminFetch(`/api/v1/admin/personas/${p.id}`, { method: "DELETE" });
      setNotice(`${p.name} deleted.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the persona.");
    } finally {
      setBusy(null);
    }
  };

  const create = async () => {
    if (!fresh.name.trim()) {
      setError("A persona needs a name.");
      return;
    }
    setBusy("__new__");
    setError(null);
    setNotice(null);
    try {
      await adminFetch("/api/v1/admin/personas", {
        method: "POST",
        body: JSON.stringify({
          name: fresh.name.trim(),
          gender: fresh.gender,
          description: fresh.description || null,
          instructions: fresh.instructions || null,
          sort_order: Number(fresh.sort_order) || 0,
        }),
      });
      setFresh(emptyDraft());
      setNotice("Persona added. Activate it when you are ready.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the persona.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-5">
      <header>
        <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">
          Intelligence
        </p>
        <h1 className="mt-1 text-[22px] font-bold text-ink">AI personas</h1>
        <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-ink/55">
          The active persona is the name, gender and tone every tenant sees. Sarah
          is the default. Only one persona can be active; the TTS voice in{" "}
          <a href="/voice" className="font-semibold text-deep-violet underline-offset-2 hover:underline">
            Voice models
          </a>{" "}
          should match the persona’s gender.
        </p>
      </header>

      {notice && (
        <p role="status" className="rounded-[2px] border border-emerald-300 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-800">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-[2px] border border-red-300 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-[12px] text-ink/50">Loading personas…</p>
      ) : (
        <div className="space-y-3">
          {personas.map((p) => {
            const d = drafts[p.id] ?? draftOf(p);
            return (
              <section
                key={p.id}
                className={`rounded-[3px] border bg-white p-4 ${
                  p.is_active ? "border-deep-violet/30" : "border-[var(--ui-line)]"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[15px] font-bold text-ink">{p.name}</h2>
                  {p.is_active ? (
                    <span className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-deep-violet">
                      Active
                    </span>
                  ) : (
                    <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/45">
                      Inactive
                    </span>
                  )}
                  <span className="ml-auto text-[10px] text-ink/35">{p.gender}</span>
                </div>

                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <label className="block text-[11px] font-semibold text-ink/55">
                    Name
                    <input
                      value={d.name}
                      onChange={(e) => setDraft(p.id, { name: e.target.value })}
                      className={`mt-1 ${INPUT}`}
                    />
                  </label>
                  <label className="block text-[11px] font-semibold text-ink/55">
                    Gender
                    <select
                      value={d.gender}
                      onChange={(e) => setDraft(p.id, { gender: e.target.value as Draft["gender"] })}
                      className={`mt-1 ${INPUT}`}
                    >
                      <option value="female">Female</option>
                      <option value="male">Male</option>
                      <option value="neutral">Neutral</option>
                    </select>
                  </label>
                  <label className="block text-[11px] font-semibold text-ink/55">
                    Description
                    <input
                      value={d.description}
                      onChange={(e) => setDraft(p.id, { description: e.target.value })}
                      className={`mt-1 ${INPUT}`}
                    />
                  </label>
                  <label className="block text-[11px] font-semibold text-ink/55">
                    Sort order
                    <input
                      type="number"
                      min={0}
                      max={1000}
                      value={d.sort_order}
                      onChange={(e) => setDraft(p.id, { sort_order: Number(e.target.value) })}
                      className={`mt-1 ${INPUT}`}
                    />
                  </label>
                </div>
                <label className="mt-2 block text-[11px] font-semibold text-ink/55">
                  Tone notes (appended to the prompt; never shown to customers)
                  <textarea
                    value={d.instructions}
                    onChange={(e) => setDraft(p.id, { instructions: e.target.value })}
                    rows={3}
                    className={`mt-1 ${INPUT}`}
                    placeholder="e.g. warm, concise, uses the customer's name occasionally; never says 'Certainly!'"
                  />
                </label>

                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={() => void save(p)}
                    disabled={busy === p.id}
                    className="rounded-full bg-deep-violet px-4 py-1.5 text-[11px] font-bold text-white disabled:opacity-50"
                  >
                    {busy === p.id ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={() => void activate(p)}
                    disabled={busy === p.id || p.is_active}
                    className="rounded-full border border-[var(--ui-line-strong)] px-4 py-1.5 text-[11px] font-semibold text-ink disabled:opacity-40"
                  >
                    {p.is_active ? "Active" : "Activate"}
                  </button>
                  <button
                    onClick={() => void remove(p)}
                    disabled={busy === p.id || p.is_active}
                    className="ml-auto rounded-full border border-red-300 px-4 py-1.5 text-[11px] font-semibold text-red-600 disabled:opacity-30"
                  >
                    Delete
                  </button>
                </div>
              </section>
            );
          })}
        </div>
      )}

      <section className="rounded-[3px] border border-[var(--ui-line)] bg-white p-4">
        <h2 className="text-[14px] font-bold text-ink">Add a persona</h2>
        <p className="mt-0.5 text-[11px] text-ink/45">
          New personas start inactive. Activate one when it is ready.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="block text-[11px] font-semibold text-ink/55">
            Name
            <input
              value={fresh.name}
              onChange={(e) => setFresh((f) => ({ ...f, name: e.target.value }))}
              className={`mt-1 ${INPUT}`}
              placeholder="Sarah"
            />
          </label>
          <label className="block text-[11px] font-semibold text-ink/55">
            Gender
            <select
              value={fresh.gender}
              onChange={(e) => setFresh((f) => ({ ...f, gender: e.target.value as Draft["gender"] }))}
              className={`mt-1 ${INPUT}`}
            >
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="neutral">Neutral</option>
            </select>
          </label>
          <label className="block text-[11px] font-semibold text-ink/55">
            Description
            <input
              value={fresh.description}
              onChange={(e) => setFresh((f) => ({ ...f, description: e.target.value }))}
              className={`mt-1 ${INPUT}`}
              placeholder="Warm, capable support teammate"
            />
          </label>
          <label className="block text-[11px] font-semibold text-ink/55">
            Sort order
            <input
              type="number"
              min={0}
              max={1000}
              value={fresh.sort_order}
              onChange={(e) => setFresh((f) => ({ ...f, sort_order: Number(e.target.value) }))}
              className={`mt-1 ${INPUT}`}
            />
          </label>
        </div>
        <label className="mt-2 block text-[11px] font-semibold text-ink/55">
          Tone notes
          <textarea
            value={fresh.instructions}
            onChange={(e) => setFresh((f) => ({ ...f, instructions: e.target.value }))}
            rows={3}
            className={`mt-1 ${INPUT}`}
          />
        </label>
        <button
          onClick={() => void create()}
          disabled={busy === "__new__"}
          className="mt-3 rounded-full bg-deep-violet px-4 py-1.5 text-[11px] font-bold text-white disabled:opacity-50"
        >
          {busy === "__new__" ? "Adding…" : "Add persona"}
        </button>
      </section>
    </div>
  );
}
