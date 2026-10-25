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

function checksFor(mode: WhatsAppMode): string[] {
  if (mode === "coexistence") {
    return [
      "The WhatsApp Business app is installed on my phone with the number I want to connect.",
      "The country code on that number is set correctly in the app.",
      "My WhatsApp Business app is version 2.24.17 or newer.",
    ];
  }
  return [
    "The number I want to use is not currently registered on WhatsApp.",
    "I can receive an SMS or call on that number right now.",
    "I can log in to the Facebook account that manages my business.",
  ];
}

export default function WhatsAppConnectFlow() {
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
      mode === "coexistence"
        ? [
            "The WhatsApp Business app installed on your phone, with the number you want to connect.",
            "The correct country code on that number.",
            "WhatsApp Business app version 2.24.17 or newer.",
            "A Facebook account that can manage your business.",
          ]
        : [
            "A phone number that is not currently registered on WhatsApp.",
            "Access to that number for the SMS or call verification.",
            "A Facebook account that can manage your business.",
          ],
    [mode]
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
      setError(e instanceof Error ? e.message : "Could not start WhatsApp connect.");
    } finally {
      setBusy(false);
    }
  };

  const finishRegistration = async () => {
    if (!pendingReg) return;
    if (!/^\d{6}$/.test(pinDraft)) {
      setError("Enter the 6-digit PIN from WhatsApp → Settings → Account → Two-step verification.");
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
      setError("Registration rejected. Check the PIN and try again (you have 14 days from signup).");
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
      setError("Could not activate that number. Try again, or pick it later on the WhatsApp page.");
    } finally {
      setBusy(false);
    }
  };

  const allChecked = checks.every(Boolean);
  const allRequirements = checksFor(mode);

  return (
    <OnboardingShell
      platform="whatsapp"
      title="Connect WhatsApp Business"
      subtitle="Let our AI answer your customers on WhatsApp — with your own number, your own business name, and a shared inbox for your team."
      steps={STEPS}
      current={step}
      onStepClick={(i) => {
        if (i < step) setStep(i);
      }}
      aside={
        step === STEP_OVERVIEW ? (
          <>
            <BenefitList
              title="Why connect WhatsApp"
              items={[
                {
                  icon: "⚡",
                  label: "Answers in seconds",
                  body: "The AI replies to every customer message, day or night, in your brand voice.",
                },
                {
                  icon: "🧵",
                  label: "One thread per customer",
                  body: "AI drafts and your team work the same conversation in the inbox.",
                },
                {
                  icon: "📱",
                  label: "Keep your number",
                  body: "Coexistence keeps the WhatsApp Business app on your phone and adds the API on top.",
                },
              ]}
            />
            <RequirementList items={requirements} />
            <GuidelineNote
              title="Connect your WhatsApp Phone Number"
              lines={[
                "Use your official business number.",
                "The number you register must not be linked to any existing WhatsApp (personal or business) account.",
                "Unlink it from any other WhatsApp account first, then come back and register.",
              ]}
            />
          </>
        ) : null
      }
    >
      {step === STEP_OVERVIEW && (
        <div>
          <StepHeading
            title="How do you want to connect?"
            body="Both options use Meta's official WhatsApp Business Platform. You can switch numbers later without losing conversations."
          />

          {alreadyConnected && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] leading-relaxed text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300">
              WhatsApp is already connected. You can reconnect a number below, or{" "}
              <Link href="/dashboard/channels/whatsapp" className="font-semibold underline underline-offset-2">
                manage it on the WhatsApp page
              </Link>
              .
            </p>
          )}

          <div className="mt-4 space-y-2.5" role="radiogroup" aria-label="Connection type">
            <ModeCard
              selected={mode === "coexistence"}
              onSelect={() => selectMode("coexistence")}
              title="Connect an existing number"
              badge="Coexistence · BETA"
              body="Keep using the WhatsApp Business app on your phone. Chats sync to Sayvors and the AI answers alongside you."
              points={[
                "No downtime — the app keeps working",
                "History sync can take up to 24 hours",
                "Best when customers already have this number",
              ]}
            />
            <ModeCard
              selected={mode === "standard"}
              onSelect={() => selectMode("standard")}
              title="Create a new number"
              badge="Cloud API"
              body="Register a fresh number for the API only. Best for a dedicated support line that does not need the phone app."
              points={[
                "Number must not be on WhatsApp yet",
                "Verified by SMS or call during signup",
                "Cleanest setup for a support team",
              ]}
            />
          </div>

          <StepActions hint="Takes about 5 minutes. Meta reviews the business details you already have.">
            <PrimaryButton onClick={() => setStep(STEP_CHECKS)}>Continue</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">Cancel</SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_CHECKS && (
        <div>
          <StepHeading
            eyebrow="Step 1 of 2"
            title="Before you begin"
            body={
              mode === "coexistence"
                ? "Confirm these three things. If any is missing, fix it in the WhatsApp Business app first — Meta will reject the connection otherwise."
                : "Confirm these three things before Meta opens its signup window."
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
          <StepActions hint="Nothing is sent to Meta until you press Proceed.">
            <PrimaryButton onClick={() => setStep(STEP_FACEBOOK)} disabled={!allChecked}>
              Proceed
            </PrimaryButton>
            <SecondaryButton onClick={() => setStep(STEP_OVERVIEW)}>Back</SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_FACEBOOK && (
        <div>
          <StepHeading
            eyebrow="Step 2 of 2"
            title="Continue with Facebook"
            body="Meta opens its own secure window where you pick the business and the number. Sayvors never sees your Facebook password."
          />
          <ul className="mt-4 space-y-2 text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              Choose the business that owns this number.
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {mode === "coexistence"
                ? "Confirm the WhatsApp Business app number you want to keep using."
                : "Enter the new number and verify it with the code Meta sends."}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              Allow the permissions Meta asks for, then come back here.
            </li>
          </ul>

          {error && <ErrorNote>{error}</ErrorNote>}

          <StepActions hint="Allow popups for this site — Meta opens the signup in a new window.">
            <PrimaryButton onClick={() => void handleConnect()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> Waiting for Meta…
                </span>
              ) : (
                "Continue with Facebook"
              )}
            </PrimaryButton>
            <SecondaryButton onClick={() => setStep(STEP_CHECKS)} disabled={busy}>
              Back
            </SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_NUMBER && (
        <div>
          <StepHeading
            eyebrow="Almost there"
            title={needsPin ? "Finish number registration" : "Which number should Sayvors use?"}
            body={
              needsPin
                ? "Meta created the number but refused to register it without two-step verification. Enter the PIN once and the number can send."
                : "We found the numbers on this WhatsApp Business account. Pick the one the AI should answer on."
            }
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          {needsPin ? (
            <div className="mt-4 rounded-xl border border-amber-300/60 bg-amber-50 p-3 dark:border-amber-500/25 dark:bg-amber-500/10">
              <label htmlFor="wa-connect-pin" className="text-[11px] font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300">
                Two-step verification PIN
              </label>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  id="wa-connect-pin"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={pinDraft}
                  onChange={(e) => setPinDraft(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="6-digit PIN"
                  className="w-32 rounded-lg border border-ink/[0.1] bg-white px-2.5 py-2 text-[13px] tabular-nums outline-none focus:border-deep-violet/40 dark:border-fog/[0.12] dark:bg-ink"
                />
                <PrimaryButton
                  onClick={() => void finishRegistration()}
                  disabled={busy || pinDraft.length !== 6}
                >
                  {busy ? "Registering…" : "Finish registration"}
                </PrimaryButton>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-amber-800/80 dark:text-amber-300/80">
                WhatsApp → Settings → Account → Two-step verification. You have 14 days from signup
                to register the number.
              </p>
            </div>
          ) : (
            <>
              {numbers.length === 0 ? (
                <p className="mt-4 rounded-lg bg-ink/[0.03] px-3 py-2.5 text-[12px] text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">
                  Meta reported the connection but no numbers are visible yet. Give it a minute and{" "}
                  <button
                    type="button"
                    onClick={() => void loadNumbers()}
                    className="font-semibold underline underline-offset-2"
                  >
                    reload
                  </button>
                  .
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
                          {n.name || "WhatsApp Business number"}
                          {n.active ? " · currently active" : ""}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </>
          )}

          {!needsPin && (
            <StepActions hint="Pick every number the AI may answer on. You can change this later.">
              <PrimaryButton
                onClick={() => void saveNumber()}
                disabled={busy || picked.length === 0}
              >
                {busy ? "Saving…" : picked.length > 1 ? `Use selected (${picked.length})` : "Use this number"}
              </PrimaryButton>
              <SecondaryButton href="/dashboard/channels/whatsapp">Manage later</SecondaryButton>
            </StepActions>
          )}
        </div>
      )}

      {step === STEP_DONE && (
        <div>
          <StepHeading
            title="WhatsApp is connected"
            body={
              mode === "coexistence"
                ? "Your number stays on the WhatsApp Business app. Chat history syncs in the background — up to 24 hours for older conversations."
                : "Meta registered the number and it can send messages now."
            }
          />
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-500/25 dark:bg-emerald-500/10">
            <p className="text-[12px] font-semibold text-emerald-800 dark:text-emerald-300">
              {saved && picked.length > 0
                ? numbers.find((n) => n.id === picked[0])?.phone ?? "Number activated"
                : "Connection stored"}
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-emerald-800/80 dark:text-emerald-300/80">
              Incoming messages will appear in the inbox. Auto-reply settings live on the WhatsApp
              page under Settings.
            </p>
          </div>
          <StepActions>
            <PrimaryButton href="/dashboard/channels/whatsapp">Open WhatsApp</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">Back to channels</SecondaryButton>
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
