"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  fetchMetaAssets,
  fetchMetaConnections,
  registerWhatsAppNumber,
  selectMetaAssets,
  type MetaAsset,
} from "@/lib/api-meta";
import LogoLoader from "@/components/LogoLoader";
import { useI18n } from "@/lib/i18n/I18nProvider";
import OnboardingShell, {
  BenefitList,
  CheckRow,
  ErrorNote,
  GuidelineNote,
  PrimaryButton,
  RequirementList,
  SecondaryButton,
  StepActions,
  StepHeading,
} from "./OnboardingShell";
import { runWhatsAppSignup, warmFacebookSdk, type WhatsAppMode } from "./metaSignup";

/*
 * WhatsApp onboarding, modelled on the Wati flow the product team asked for:
 * a benefits page, a "Step 1 of 2" pre-flight, the Meta hand-off, then the
 * number picker. The connect button lives on the channels card and only
 * lands here — the cards never open a popup themselves.
 */

const STEPS = [
  { key: "start", label: "Get started" },
  { key: "checks", label: "Before you begin" },
  { key: "facebook", label: "Facebook" },
  { key: "number", label: "Number" },
  { key: "done", label: "Done" },
];

const STEP_OVERVIEW = 0;
const STEP_CHECKS = 1;
const STEP_FACEBOOK = 2;
const STEP_NUMBER = 3;
const STEP_DONE = 4;

function checksFor(mode: WhatsAppMode, c: ReturnType<typeof useI18n>["t"]["dashboard"]["connect"]["whatsapp"]): string[] {
  if (mode === "coexistence") {
    return [...c.checksCoexistence];
  }
  return [...c.checksStandard];
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

export default function WhatsAppConnectFlow() {
  const { t, locale } = useI18n();
  const w = t.dashboard.connect.whatsapp;
  const STEPS = [
    { key: "start", label: w.steps.start },
    { key: "checks", label: w.steps.checks },
    { key: "facebook", label: w.steps.facebook },
    { key: "number", label: w.steps.number },
    { key: "done", label: w.steps.done },
  ];
  const [step, setStep] = useState(STEP_OVERVIEW);
  const [mode, setMode] = useState<WhatsAppMode>("coexistence");
  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [alreadyConnected, setAlreadyConnected] = useState(false);
  const [needsPin, setNeedsPin] = useState(false);
  const [pinDraft, setPinDraft] = useState("");
  const [pendingReg, setPendingReg] = useState<string | null>(null);

  const [numbers, setNumbers] = useState<MetaAsset[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  const requirements = useMemo(
    () =>
      mode === "coexistence" ? [...w.reqCoexistence] : [...w.reqStandard],
    [mode, w],
  );

  const loadNumbers = useCallback(async () => {
    try {
      const r = await fetchMetaAssets("whatsapp");
      const phones = (r.assets ?? []).filter((a) => a.asset_type === "phone_number");
      setNumbers(phones);
      // Pre-check whatever is already active so a reconnect does not silently
      // deselect the number the tenant is actually using.
      setPicked(phones.filter((a) => a.active).map((a) => a.id));
    } catch {
      setNumbers([]);
    }
  }, []);

  useEffect(() => {
    warmFacebookSdk();
    let cancelled = false;
    (async () => {
      try {
        const conns = await fetchMetaConnections();
        if (cancelled) return;
        const wa = (conns.connections ?? []).find((c) => c.provider === "whatsapp");
        setAlreadyConnected(Boolean(wa && wa.status !== "revoked"));
      } catch {
        /* backend down — the flow still explains itself */
      }
      if (!cancelled) await loadNumbers();
    })();
    return () => {
      cancelled = true;
    };
  }, [loadNumbers]);

  const selectMode = (next: WhatsAppMode) => {
    setMode(next);
    setChecks([false, false, false]);
  };

  const handleConnect = async () => {
    setBusy(true);
    setError(null);
    try {
      // Must run from this click: runWhatsAppSignup opens the popup before
      // its first await.
      const result = await runWhatsAppSignup(mode);
      if (result.needsPin) {
        setNeedsPin(true);
        setPendingReg(result.pendingRegistrationId);
      }
      await loadNumbers();
      setStep(STEP_NUMBER);
    } catch (e) {
      setError(e instanceof Error ? e.message : w.errors.start);
    } finally {
      setBusy(false);
    }
  };

  const finishRegistration = async () => {
    if (!pendingReg) return;
    if (!/^\d{6}$/.test(pinDraft)) {
      setError(w.errors.enterPin);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerWhatsAppNumber(pendingReg, pinDraft);
      setPinDraft("");
      setPendingReg(null);
      setNeedsPin(false);
      await loadNumbers();
    } catch {
      setError(w.errors.regRejected);
    } finally {
      setBusy(false);
    }
  };

  const saveNumber = async () => {
    setBusy(true);
    setError(null);
    try {
      await selectMetaAssets("whatsapp", picked);
      setSaved(true);
      setStep(STEP_DONE);
    } catch {
      setError(w.errors.saveNumber);
    } finally {
      setBusy(false);
    }
  };

  const allChecked = checks.every(Boolean);
  const allRequirements = checksFor(mode, w);

  return (
    <OnboardingShell
      platform="whatsapp"
      title={w.title}
      subtitle={w.subtitle}
      steps={STEPS}
      current={step}
      onStepClick={(i) => {
        if (i < step) setStep(i);
      }}
      aside={
        step === STEP_OVERVIEW ? (
          <>
            <BenefitList
              title={w.benefitsTitle}
              items={w.benefits.map((b, i) => ({ icon: ["⚡", "🧵", "📱"][i], label: b.label, body: b.body }))}
            />
            <RequirementList items={requirements} />
            <GuidelineNote
              title={w.guidelineTitle}
              lines={[...w.guideline]}
            />
          </>
        ) : null
      }
    >
      {step === STEP_OVERVIEW && (
        <div>
          <StepHeading
            title={w.overviewTitle}
            body={w.overviewBody}
          />

          {alreadyConnected && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] leading-relaxed text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300">
              {w.already}{" "}
              <Link href="/dashboard/channels/whatsapp" className="font-semibold underline underline-offset-2">
                {w.alreadyLink}
              </Link>
              .
            </p>
          )}

          <div className="mt-4 space-y-2.5" role="radiogroup" aria-label="Connection type">
            <ModeCard
              selected={mode === "coexistence"}
              onSelect={() => selectMode("coexistence")}
              title={w.modeExisting}
              badge={w.modeExistingBadge}
              body={w.modeExistingBody}
              points={[...w.modeExistingPoints]}
            />
            <ModeCard
              selected={mode === "standard"}
              onSelect={() => selectMode("standard")}
              title={w.modeNew}
              badge={w.modeNewBadge}
              body={w.modeNewBody}
              points={[...w.modeNewPoints]}
            />
          </div>

          <StepActions hint={w.overviewHint}>
            <PrimaryButton onClick={() => setStep(STEP_CHECKS)}>{t.dashboard.connect.continue}</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">{t.common.cancel}</SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_CHECKS && (
        <div>
          <StepHeading
            eyebrow={w.stepOne}
            title={w.checksTitle}
            body={
              mode === "coexistence"
                ? w.checksBodyCoexistence
                : w.checksBodyStandard
            }
          />
          <div className="mt-4 space-y-2">
            {allRequirements.map((item, i) => (
              <CheckRow
                key={item}
                checked={checks[i] ?? false}
                onChange={(next) =>
                  setChecks((prev) => {
                    const copy = [...prev];
                    copy[i] = next;
                    return copy;
                  })
                }
              >
                {item}
              </CheckRow>
            ))}
          </div>
          <StepActions hint={w.checksHint}>
            <PrimaryButton onClick={() => setStep(STEP_FACEBOOK)} disabled={!allChecked}>
              {t.dashboard.connect.proceed}
            </PrimaryButton>
            <SecondaryButton onClick={() => setStep(STEP_OVERVIEW)}>{t.common.back}</SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_FACEBOOK && (
        <div>
          <StepHeading
            eyebrow={w.stepTwo}
            title={w.fbTitle}
            body={w.fbBody}
          />
          <ul className="mt-4 space-y-2 text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {w.fbBullets[0]}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {mode === "coexistence" ? w.fbBullets[1] : w.fbBulletsStandard[1]}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {w.fbBullets[2]}
            </li>
          </ul>

          {error && <ErrorNote>{error}</ErrorNote>}

          <StepActions hint={w.fbHint}>
            <PrimaryButton onClick={() => void handleConnect()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> {w.waitingMeta}
                </span>
              ) : (
                w.fbTitle
              )}
            </PrimaryButton>
            <SecondaryButton onClick={() => setStep(STEP_CHECKS)} disabled={busy}>
              {t.common.back}
            </SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_NUMBER && (
        <div>
          <StepHeading
            eyebrow="Almost there"
            title={needsPin ? w.pinTitle : w.numberTitle}
            body={
              needsPin ? w.pinBody : w.numberBody
            }
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          {needsPin ? (
            <div className="mt-4 rounded-xl border border-amber-300/60 bg-amber-50 p-3 dark:border-amber-500/25 dark:bg-amber-500/10">
              <label htmlFor="wa-connect-pin" className="text-[11px] font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300">
                {w.pinLabel}
              </label>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  id="wa-connect-pin"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={pinDraft}
                  onChange={(e) => setPinDraft(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder={w.pinPh}
                  className="w-32 rounded-lg border border-ink/[0.1] bg-white px-2.5 py-2 text-[13px] tabular-nums outline-none focus:border-deep-violet/40 dark:border-fog/[0.12] dark:bg-ink"
                />
                <PrimaryButton
                  onClick={() => void finishRegistration()}
                  disabled={busy || pinDraft.length !== 6}
                >
                  {busy ? w.registering : w.finishReg}
                </PrimaryButton>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-amber-800/80 dark:text-amber-300/80">
                {w.pinHint}
              </p>
            </div>
          ) : (
            <>
              {numbers.length === 0 ? (
                <p className="mt-4 rounded-lg bg-ink/[0.03] px-3 py-2.5 text-[12px] text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">
                  {w.noNumbers}{" "}
                  <button
                    type="button"
                    onClick={() => void loadNumbers()}
                    className="font-semibold underline underline-offset-2"
                  >
                    {w.reload}
                  </button>
                  {w.dot}
                </p>
              ) : (
                <div className="mt-4 space-y-2">
                  {numbers.map((n) => (
                    <label
                      key={n.id}
                      className="flex cursor-pointer items-center gap-3 rounded-lg border border-ink/[0.06] bg-white px-3 py-2.5 transition hover:border-deep-violet/25 dark:border-fog/[0.08] dark:bg-ink"
                    >
                      <input
                        type="checkbox"
                        checked={picked.includes(n.id)}
                        onChange={() =>
                          setPicked((prev) =>
                            prev.includes(n.id) ? prev.filter((x) => x !== n.id) : [...prev, n.id]
                          )
                        }
                        className="h-4 w-4 shrink-0 accent-[#5b2d8e]"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold text-ink dark:text-fog">
                          {n.phone || n.name || n.external_asset_id}
                        </span>
                        <span className="block truncate text-[11px] text-ink/45 dark:text-fog/45">
                          {n.name || w.waNumber}
                          {n.active ? w.currentlyActive : ""}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </>
          )}

          {!needsPin && (
            <StepActions hint={w.pickHint}>
              <PrimaryButton
                onClick={() => void saveNumber()}
                disabled={busy || picked.length === 0}
              >
                {busy ? t.dashboard.connect.saving : picked.length > 1 ? fill(w.useSelected, { count: picked.length }) : w.useNumber}
              </PrimaryButton>
              <SecondaryButton href="/dashboard/channels/whatsapp">{w.manageLater}</SecondaryButton>
            </StepActions>
          )}
        </div>
      )}

      {step === STEP_DONE && (
        <div>
          <StepHeading
            title={w.doneTitle}
            body={
              mode === "coexistence"
                ? w.doneBodyCoexistence
                : w.doneBodyStandard
            }
          />
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-500/25 dark:bg-emerald-500/10">
            <p className="text-[12px] font-semibold text-emerald-800 dark:text-emerald-300">
              {saved && picked.length > 0
                ? numbers.find((n) => n.id === picked[0])?.phone ?? w.activated
                : w.stored}
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-emerald-800/80 dark:text-emerald-300/80">
              {w.doneDetail}
            </p>
          </div>
          <StepActions>
            <PrimaryButton href="/dashboard/channels/whatsapp">{w.openWhatsApp}</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">{w.backChannels}</SecondaryButton>
          </StepActions>
        </div>
      )}
    </OnboardingShell>
  );
}

function ModeCard({
  selected,
  onSelect,
  title,
  badge,
  body,
  points,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  badge: string;
  body: string;
  points: string[];
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={`w-full rounded-xl border p-3.5 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
        selected
          ? "border-deep-violet/40 bg-deep-violet/[0.04]"
          : "border-ink/[0.08] bg-white hover:border-deep-violet/25 dark:border-fog/[0.1] dark:bg-ink"
      }`}
    >
      <span className="flex flex-wrap items-center gap-2">
        <span
          aria-hidden
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
            selected ? "border-deep-violet bg-deep-violet" : "border-ink/25 dark:border-fog/25"
          }`}
        >
          {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
        </span>
        <span className="text-[13.5px] font-semibold text-ink dark:text-fog">{title}</span>
        <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50">
          {badge}
        </span>
      </span>
      <span className="mt-1.5 block text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
        {body}
      </span>
      <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {points.map((p) => (
          <span key={p} className="text-[11px] text-ink/40 dark:text-fog/40">
            · {p}
          </span>
        ))}
      </span>
    </button>
  );
}
