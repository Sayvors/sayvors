"use client";

import { useMemo, useState } from "react";

const DEMO = [
  { name: "order_update", lang: "en", status: "approved", updated: "2026-09-20" },
  { name: "promo_oct", lang: "en", status: "pending", updated: "2026-10-01" },
  { name: "support_followup", lang: "ar", status: "approved", updated: "2026-09-11" },
];

export default function TemplatesList() {
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return DEMO;
    return DEMO.filter((r) => r.name.toLowerCase().includes(t));
  }, [q]);

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search templates…" aria-label="Search templates" className="min-h-11 min-w-0 flex-1 rounded-xl border border-black/10 bg-white px-3 text-[13px] outline-none focus:border-[#25D366]" />
        <span className="text-[12px] text-black/45">{rows.length} shown</span>
      </div>
      {rows.length === 0 ? (
        <div className="py-8 text-center">
          <p className="font-bold">No templates match “{q}”.</p>
          <button onClick={() => setQ("")} className="mt-2 min-h-11 rounded-xl border border-black/10 px-4 text-[13px] font-semibold">Clear search</button>
        </div>
      ) : (
        <ul className="mt-3 divide-y divide-black/[0.05]">
          {rows.map((r) => (
            <li key={r.name} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-bold">{r.name}</p>
                <p className="text-[11px] text-black/45">{r.lang} · updated {r.updated}</p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${r.status === "approved" ? "bg-emerald-500/15 text-emerald-700" : "bg-amber-500/15 text-amber-700"}`}>{r.status}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-black/40">Read-only in v1 — full Meta template manager ships next.</p>
    </div>
  );
}
