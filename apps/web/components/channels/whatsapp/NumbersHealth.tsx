"use client";

import { useState } from "react";
import {
  deregisterWhatsAppNumber,
  registerWhatsAppNumber,
  requestWhatsAppCode,
  setWhatsAppTwoStepPin,
  validateMeta,
  verifyWhatsAppCode,
  type MetaAsset,
} from "@/lib/api-meta";
import { useI18n } from "@/lib/i18n/I18nProvider";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

type RegState = "idle" | "registering" | "success" | "error";
type CodeState = "idle" | "sending" | "sent" | "verifying" | "verified";
type PinState = "idle" | "saving" | "saved";

export default function NumbersHealth({
  numbers,
  activeId,
  onRefresh,
}: {
  numbers: MetaAsset[];
  activeId: string;
  onRefresh: () => Promise<void>;
}) {
  const { t } = useI18n();
  const ns = t.dashboard.whatsapp.numbers;
  const [busy, setBusy] = useState<string | null>(null);
  const [pin, setPin] = useState<Record<string, string>>({});
  const [reg, setReg] = useState<Record<string, RegState>>({});
  const [regError, setRegError] = useState<Record<string, string>>({});
  const [method, setMethod] = useState<Record<string, "SMS" | "VOICE">>({});
  const [code, setCode] = useState<Record<string, string>>({});
  const [codeState, setCodeState] = useState<Record<string, CodeState>>({});
  const [codeError, setCodeError] = useState<Record<string, string>>({});
  const [twoStepPin, setTwoStepPin] = useState<Record<string, string>>({});
  const [twoStepState, setTwoStepState] = useState<Record<string, PinState>>({});
  const [twoStepError, setTwoStepError] = useState<Record<string, string>>({});
  const [deregistering, setDeregistering] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const sixDigits = (value: string) => value.replace(/\D/g, "").slice(0, 6);

  const register = async (id: string) => {
    const p = (pin[id] ?? "").trim();
    if (!/^\d{6}$/.test(p)) {
      setRegError((m) => ({ ...m, [id]: ns.pinDigits }));
      setReg((s) => ({ ...s, [id]: "error" }));
      return;
    }
    setReg((s) => ({ ...s, [id]: "registering" }));
    setRegError((m) => ({ ...m, [id]: "" }));
    try {
      await registerWhatsAppNumber(id, p);
      setReg((s) => ({ ...s, [id]: "success" }));
      setMsg(null);
      await onRefresh();
    } catch (e) {
      setRegError((m) => ({
        ...m,
        [id]: e instanceof Error ? e.message.slice(0, 200) : ns.regFailed,
      }));
      setReg((s) => ({ ...s, [id]: "error" }));
    }
  };

  const sendCode = async (id: string) => {
    setCodeState((s) => ({ ...s, [id]: "sending" }));
    setCodeError((m) => ({ ...m, [id]: "" }));
    try {
      await requestWhatsAppCode(id, method[id] ?? "SMS");
      setCodeState((s) => ({ ...s, [id]: "sent" }));
    } catch (e) {
      setCodeError((m) => ({
        ...m,
        [id]: e instanceof Error ? e.message.slice(0, 200) : ns.codeFailed,
      }));
      setCodeState((s) => ({ ...s, [id]: "idle" }));
    }
  };

  const verify = async (id: string) => {
    const value = (code[id] ?? "").trim();
    if (!/^\d{6}$/.test(value)) {
      setCodeError((m) => ({ ...m, [id]: ns.codeDigits }));
      return;
    }
    setCodeState((s) => ({ ...s, [id]: "verifying" }));
    setCodeError((m) => ({ ...m, [id]: "" }));
    try {
      await verifyWhatsAppCode(id, value);
      setCodeState((s) => ({ ...s, [id]: "verified" }));
      await onRefresh();
    } catch (e) {
      setCodeError((m) => ({
        ...m,
        [id]: e instanceof Error ? e.message.slice(0, 200) : ns.verifyFailed,
      }));
      setCodeState((s) => ({ ...s, [id]: "sent" }));
    }
  };

  const saveTwoStep = async (id: string) => {
    const value = (twoStepPin[id] ?? "").trim();
    if (!/^\d{6}$/.test(value)) {
      setTwoStepError((m) => ({ ...m, [id]: ns.pinDigitsShort }));
      return;
    }
    setTwoStepState((s) => ({ ...s, [id]: "saving" }));
    setTwoStepError((m) => ({ ...m, [id]: "" }));
    try {
      await setWhatsAppTwoStepPin(id, value);
      setTwoStepState((s) => ({ ...s, [id]: "saved" }));
      setTwoStepPin((p) => ({ ...p, [id]: "" }));
    } catch (e) {
      setTwoStepError((m) => ({
        ...m,
        [id]: e instanceof Error ? e.message.slice(0, 200) : ns.pinUpdateFailed,
      }));
      setTwoStepState((s) => ({ ...s, [id]: "idle" }));
    }
  };

  const deregister = async (id: string) => {
    if (!window.confirm(ns.dereConfirm)) {
      return;
    }
    setDeregistering(id);
    setMsg(null);
    try {
      await deregisterWhatsAppNumber(id);
      await onRefresh();
      setMsg(ns.dereDone);
    } catch (e) {
      setMsg(e instanceof Error ? e.message.slice(0, 200) : ns.deregFailed);
    } finally {
      setDeregistering(null);
    }
  };

  const revalidate = async () => {
    setBusy("all");
    try {
      await validateMeta("whatsapp");
      await onRefresh();
      setMsg(ns.healthRefreshed);
    } catch (e) {
      setMsg(e instanceof Error ? e.message.slice(0, 200) : ns.refreshFailed);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3" style={{ fontFamily: '"Segoe UI",Helvetica Neue,Helvetica,Arial,sans-serif' }}>
      {msg && <p role="status" className="mx-auto max-w-md rounded-lg bg-[var(--wa-warn-bg)] px-4 py-2.5 text-[13px] text-[var(--wa-warn-text)] shadow">{msg}</p>}
      {numbers.map((n) => {
        const state = reg[n.external_asset_id] ?? "idle";
        const cState = codeState[n.external_asset_id] ?? "idle";
        const pState = twoStepState[n.external_asset_id] ?? "idle";
        return (
          <div key={n.external_asset_id} className={`rounded-lg bg-[var(--wa-panel)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)] ${n.external_asset_id === activeId ? "ring-2 ring-[var(--wa-accent)]" : ""}`}>
            <div className="flex flex-wrap items-center gap-3">
              <span className={`h-2.5 w-2.5 rounded-full ${n.active ? "bg-emerald-500" : "bg-amber-500"}`} />
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-bold text-[var(--wa-text)]">{n.phone || n.name || n.external_asset_id}</p>
                <p className="truncate text-[11px] text-[var(--wa-text-2)]">{n.name || "WhatsApp number"} · {n.status}</p>
              </div>
              <button onClick={revalidate} disabled={busy !== null} className="min-h-11 rounded-xl border border-[var(--wa-border)] px-3 text-[12px] font-semibold text-[var(--wa-text)] disabled:opacity-50">
                {busy === "all" ? ns.checking : ns.refresh}
              </button>
            </div>

            <details className="mt-3 rounded-xl border border-[var(--wa-border)] p-3">
              <summary className="cursor-pointer text-[12px] font-bold text-[var(--wa-text)]">
                {ns.lifecycle}
              </summary>

              <div className="mt-3 space-y-3">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--wa-text-2)]">
                    {ns.verify}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <select
                      value={method[n.external_asset_id] ?? "SMS"}
                      onChange={(e) => setMethod((m) => ({ ...m, [n.external_asset_id]: e.target.value as "SMS" | "VOICE" }))}
                      aria-label={fill(ns.delivery, { phone: n.phone ?? n.external_asset_id })}
                      className="min-h-11 rounded-xl border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3 text-[13px] text-[var(--wa-text)]"
                    >
                      <option value="SMS">{ns.sms}</option>
                      <option value="VOICE">{ns.voice}</option>
                    </select>
                    <button
                      onClick={() => sendCode(n.external_asset_id)}
                      disabled={cState === "sending" || cState === "verifying"}
                      className="min-h-11 rounded-full border border-[var(--wa-border)] px-4 text-[12px] font-semibold text-[var(--wa-text)] disabled:opacity-50"
                    >
                      {cState === "sending" ? ns.requesting : ns.requestCode}
                    </button>
                    {(cState === "sent" || cState === "verifying" || cState === "verified") && (
                      <>
                        <input
                          value={code[n.external_asset_id] ?? ""}
                          onChange={(e) => setCode((c) => ({ ...c, [n.external_asset_id]: sixDigits(e.target.value) }))}
                          inputMode="numeric"
                          maxLength={6}
                          placeholder={ns.codePh}
                          aria-label={fill(ns.codeAria, { phone: n.phone ?? n.external_asset_id })}
                          className="min-h-11 w-36 rounded-xl border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3 text-[13px] tracking-widest text-[var(--wa-text)]"
                        />
                        <button
                          onClick={() => verify(n.external_asset_id)}
                          disabled={cState === "verifying" || cState === "verified"}
                          className="min-h-11 rounded-full bg-[var(--wa-accent)] px-4 text-[12px] font-semibold text-white disabled:opacity-50"
                        >
                          {cState === "verified" ? ns.verified : cState === "verifying" ? ns.verifying : ns.verifyBtn}
                        </button>
                      </>
                    )}
                  </div>
                  {codeError[n.external_asset_id] && (
                    <p role="alert" className="mt-1 text-[12px] font-medium text-[var(--wa-danger)]">{codeError[n.external_asset_id]}</p>
                  )}
                </div>

                <div>
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--wa-text-2)]">
                    {ns.registerTitle}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <input
                      value={pin[n.external_asset_id] ?? ""}
                      onChange={(e) => setPin((p) => ({ ...p, [n.external_asset_id]: sixDigits(e.target.value) }))}
                      inputMode="numeric"
                      maxLength={6}
                      placeholder={ns.pinPh}
                      aria-label={fill(ns.pinAria, { phone: n.phone ?? n.external_asset_id })}
                      className="min-h-11 w-36 rounded-xl border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3 text-[13px] tracking-widest text-[var(--wa-text)]"
                    />
                    <button
                      onClick={() => register(n.external_asset_id)}
                      disabled={state === "registering"}
                      className="min-h-11 rounded-full bg-[var(--wa-accent)] px-5 text-[12px] font-semibold text-white disabled:opacity-50"
                    >
                      {state === "registering" ? ns.registering : ns.register}
                    </button>
                    {state === "success" && (
                      <span role="status" className="text-[12px] font-semibold text-[var(--wa-ok-text)]">
                        {ns.registered}
                      </span>
                    )}
                  </div>
                  {state === "error" && regError[n.external_asset_id] && (
                    <p role="alert" className="mt-1 text-[12px] font-medium text-[var(--wa-danger)]">{regError[n.external_asset_id]}</p>
                  )}
                  <p className="mt-1 text-[11px] text-[var(--wa-text-2)]">
                    {ns.reread}
                  </p>
                </div>

                <div>
                  <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--wa-text-2)]">
                    {ns.twoStep}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <input
                      value={twoStepPin[n.external_asset_id] ?? ""}
                      onChange={(e) => setTwoStepPin((p) => ({ ...p, [n.external_asset_id]: sixDigits(e.target.value) }))}
                      inputMode="numeric"
                      maxLength={6}
                      placeholder={ns.newPinPh}
                      aria-label={fill(ns.twoStepAria, { phone: n.phone ?? n.external_asset_id })}
                      className="min-h-11 w-40 rounded-xl border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3 text-[13px] tracking-widest text-[var(--wa-text)]"
                    />
                    <button
                      onClick={() => saveTwoStep(n.external_asset_id)}
                      disabled={pState === "saving"}
                      className="min-h-11 rounded-full border border-[var(--wa-border)] px-4 text-[12px] font-semibold text-[var(--wa-text)] disabled:opacity-50"
                    >
                      {pState === "saving" ? ns.saving : pState === "saved" ? ns.saved : ns.savePin}
                    </button>
                  </div>
                  {twoStepError[n.external_asset_id] && (
                    <p role="alert" className="mt-1 text-[12px] font-medium text-[var(--wa-danger)]">{twoStepError[n.external_asset_id]}</p>
                  )}
                  <p className="mt-1 text-[11px] text-[var(--wa-text-2)]">
                    {ns.twoStepNote}
                  </p>
                </div>

                <div className="border-t border-[var(--wa-border)] pt-3">
                  <button
                    onClick={() => deregister(n.external_asset_id)}
                    disabled={deregistering === n.external_asset_id}
                    className="min-h-11 rounded-full border border-[var(--wa-danger)] px-4 text-[12px] font-semibold text-[var(--wa-danger)] disabled:opacity-50"
                  >
                    {deregistering === n.external_asset_id ? ns.deregistering : ns.deregister}
                  </button>
                  <p className="mt-1 text-[11px] text-[var(--wa-text-2)]">
                    {ns.deregNote}
                  </p>
                </div>
              </div>
            </details>
          </div>
        );
      })}
    </div>
  );
}
