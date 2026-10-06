"use client";

import { useState } from "react";
import { registerWhatsAppNumber, validateMeta, type MetaAsset } from "@/lib/api-meta";

export default function NumbersHealth({ numbers, activeId }: { numbers: MetaAsset[]; activeId: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [pin, setPin] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const register = async (id: string) => {
    const p = (pin[id] ?? "").trim();
    if (!/^\d{6}$/.test(p)) {
      setMsg("PIN must be exactly 6 digits — paste allowed.");
      return;
    }
    setBusy(id);
    try {
      await registerWhatsAppNumber(id, p);
      setMsg("Number registered — it can send now.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message.slice(0, 200) : "Registration failed — try again.");
    } finally {
      setBusy(null);
    }
  };

  const revalidate = async () => {
    setBusy("all");
    try {
      await validateMeta("whatsapp");
      setMsg("Health refreshed.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message.slice(0, 200) : "Refresh failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3" style={{ fontFamily: '"Segoe UI",Helvetica Neue,Helvetica,Arial,sans-serif' }}>
      {msg && <p role="status" className="mx-auto max-w-md rounded-lg bg-[#fff3cd] px-4 py-2.5 text-[13px] text-[#664d03] shadow">{msg}</p>}
      {numbers.map((n) => (
        <div key={n.external_asset_id} className={`rounded-lg bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)] ${n.external_asset_id === activeId ? "ring-2 ring-[#00a884]" : ""}`}>
          <div className="flex flex-wrap items-center gap-3">
            <span className={`h-2.5 w-2.5 rounded-full ${n.active ? "bg-emerald-500" : "bg-amber-500"}`} />
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-bold">{n.phone || n.name || n.external_asset_id}</p>
              <p className="truncate text-[11px] text-black/45">WABA {n.external_asset_id.slice(0, 10)}… · {n.status}</p>
            </div>
            <button onClick={revalidate} disabled={busy !== null} className="min-h-11 rounded-xl border border-black/10 px-3 text-[12px] font-semibold disabled:opacity-50">
              {busy === "all" ? "Checking…" : "Refresh"}
            </button>
          </div>
          {!n.active && (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-amber-50 p-3">
              <input
                value={pin[n.external_asset_id] ?? ""}
                onChange={(e) => setPin((p) => ({ ...p, [n.external_asset_id]: e.target.value.replace(/\D/g, "").slice(0, 6) }))}
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                placeholder="6-digit PIN"
                aria-label={`PIN for ${n.phone ?? n.external_asset_id}`}
                className="min-h-11 w-36 rounded-xl border border-black/10 bg-white px-3 text-[13px] tracking-widest"
              />
              <button onClick={() => register(n.external_asset_id)} disabled={busy === n.external_asset_id} className="min-h-11 rounded-full bg-[#00a884] px-5 text-[12px] font-semibold text-white disabled:opacity-50">
                {busy === n.external_asset_id ? "Registering…" : "Register"}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
