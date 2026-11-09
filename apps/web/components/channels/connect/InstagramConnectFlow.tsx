"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  discoverInstagram,
  fetchMetaAssets,
  fetchMetaConnections,
  selectMetaAssets,
  type MetaAsset,
} from "@/lib/api-meta";
import LogoLoader from "@/components/LogoLoader";
import { useI18n } from "@/lib/i18n/I18nProvider";
import AssetPicker from "./AssetPicker";
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
import { startMetaOAuth, warmFacebookSdk } from "./metaSignup";

/*
 * Instagram onboarding.
 *
 * Instagram messaging and comments ride the parent Facebook Page's token, so
 * Meta's flow is: connect Facebook, then discover the professional accounts
 * linked to those Pages. The backend returns
 * `meta_connected=facebook&next=instagram_select` for that hand-off.
 */

const STEP_OVERVIEW = 0;
const STEP_CHECKS = 1;
const STEP_FACEBOOK = 2;
const STEP_ACCOUNTS = 3;
const STEP_DONE = 4;

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

export default function InstagramConnectFlow() {
  const params = useSearchParams();
  const { t } = useI18n();
  const g = t.dashboard.connect.instagram;
  const STEPS = [
    { key: "start", label: g.steps.start },
    { key: "checks", label: g.steps.checks },
    { key: "facebook", label: g.steps.facebook },
    { key: "accounts", label: g.steps.accounts },
    { key: "done", label: g.steps.done },
  ];
  const CHECKS = [...g.checks];
  const [step, setStep] = useState(STEP_OVERVIEW);
  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alreadyConnected, setAlreadyConnected] = useState(false);
  const [accounts, setAccounts] = useState<MetaAsset[]>([]);
  const [picked, setPicked] = useState<string[]>([]);

  const loadAccounts = useCallback(async () => {
    try {
      const r = await fetchMetaAssets("instagram");
      const list = r.assets ?? [];
      setAccounts(list);
      setPicked(list.filter((a) => a.active).map((a) => a.id));
    } catch {
      setAccounts([]);
    }
  }, []);

  const discover = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await discoverInstagram();
      await loadAccounts();
      if (res.assets.length === 0) {
        setError(g.errors.noneFound);
      }
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : g.errors.discover
      );
    } finally {
      setBusy(false);
    }
  }, [loadAccounts]);

  useEffect(() => {
    warmFacebookSdk();
    let cancelled = false;
    (async () => {
      const connected = params.get("meta_connected");
      const handoff = params.get("next");
      const failure = params.get("meta_error");
      const discovery = params.get("discovery_error");

      if (connected || failure || discovery) {
        try {
          window.history.replaceState(null, "", window.location.pathname);
        } catch {
          /* keep params — worst case a refresh re-runs discovery */
        }
      }

      if (failure) {
        setError(fill(g.errors.rejected, { code: failure }));
        setStep(STEP_FACEBOOK);
      }
      if (discovery) {
        setError(
          fill(g.errors.discovery, { code: discovery }),
        );
        setStep(STEP_ACCOUNTS);
      }
      if (connected === "facebook" && handoff === "instagram_select") {
        setAlreadyConnected(true);
        setStep(STEP_ACCOUNTS);
        await discover();
        return;
      }

      try {
        const conns = await fetchMetaConnections();
        if (cancelled) return;
        const ig = (conns.connections ?? []).find((c) => c.provider === "instagram");
        setAlreadyConnected(Boolean(ig && ig.status !== "revoked"));
        await loadAccounts();
      } catch {
        /* backend down — the flow still explains itself */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    setBusy(true);
    setError(null);
    try {
      await startMetaOAuth("instagram", "/dashboard/channels/instagram/connect");
    } catch (e) {
      setError(e instanceof Error ? e.message : g.errors.start);
      setBusy(false);
    }
  };

  const saveAccounts = async () => {
    setBusy(true);
    setError(null);
    try {
      await selectMetaAssets("instagram", picked);
      setStep(STEP_DONE);
    } catch {
      setError(g.errors.save);
    } finally {
      setBusy(false);
    }
  };

  const allChecked = checks.every(Boolean);

  return (
    <OnboardingShell
      platform="instagram"
      title={g.title}
      subtitle={g.subtitle}
      steps={STEPS}
      current={step}
      onStepClick={(i) => {
        if (i < step) setStep(i);
      }}
      aside={
        step === STEP_OVERVIEW ? (
          <>
            <BenefitList
              title={g.benefitsTitle}
              items={g.benefits.map((b, i) => ({ icon: ["💬", "✉️", "📊"][i], label: b.label, body: b.body }))}
            />
            <RequirementList
              items={[...g.requirements]}
            />
            <GuidelineNote
              title={g.guidelineTitle}
              lines={[...g.guideline]}
            />
          </>
        ) : null
      }
    >
      {step === STEP_OVERVIEW && (
        <div>
          <StepHeading
            title={g.overviewTitle}
            body={g.overviewBody}
          />

          {alreadyConnected && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] leading-relaxed text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300">
              {g.already}{" "}
              <Link href="/dashboard/channels/instagram" className="font-semibold underline underline-offset-2">
                {g.alreadyLink}
              </Link>{" "}
              {g.alreadyTail}
            </p>
          )}

          <ul className="mt-4 space-y-2 text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {g.bullets[0]}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {g.bullets[1]}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {g.bullets[2]}
            </li>
          </ul>

          <StepActions hint={g.overviewHint}>
            <PrimaryButton onClick={() => setStep(STEP_CHECKS)}>{t.dashboard.connect.continue}</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">{t.common.cancel}</SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_CHECKS && (
        <div>
          <StepHeading
            eyebrow={g.stepOne}
            title={g.checksTitle}
            body={g.checksBody}
          />
          <div className="mt-4 space-y-2">
            {CHECKS.map((item, i) => (
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
          <StepActions hint={g.checksHint}>
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
            eyebrow={g.stepTwo}
            title={g.fbTitle}
            body={g.fbBody}
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          <StepActions hint={g.fbHint}>
            <PrimaryButton onClick={() => void handleConnect()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> {g.opening}
                </span>
              ) : (
                g.fbTitle
              )}
            </PrimaryButton>
            <SecondaryButton onClick={() => setStep(STEP_CHECKS)} disabled={busy}>
              {t.common.back}
            </SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_ACCOUNTS && (
        <div>
          <StepHeading
            eyebrow={t.dashboard.connect.almostThere}
            title={g.accountsTitle}
            body={g.accountsBody}
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          <div className="mt-4">
            <SecondaryButton onClick={() => void discover()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> {g.looking}
                </span>
              ) : (
                g.discoverAgain
              )}
            </SecondaryButton>
          </div>

          <div className="mt-4">
            <AssetPicker
              eyebrow={g.accountsEyebrow}
              title={g.discoveredTitle}
              body={g.discoveredBody}
              emptyText={g.discoveredEmpty}
              assets={accounts}
              picked={picked}
              onToggle={(id) =>
                setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
              }
              onSave={() => void saveAccounts()}
              onBack={() => setStep(STEP_FACEBOOK)}
              busy={busy}
              error={null}
              savedLabel={g.discoveredSaved}
            />
          </div>
        </div>
      )}

      {step === STEP_DONE && (
        <div>
          <StepHeading
            title={g.doneTitle}
            body={g.doneBody}
          />
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-500/25 dark:bg-emerald-500/10">
            <p className="text-[12px] font-semibold text-emerald-800 dark:text-emerald-300">
              {fill(g.activeN, { count: picked.length })}
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-emerald-800/80 dark:text-emerald-300/80">
              {g.doneDetail}
            </p>
          </div>
          <StepActions>
            <PrimaryButton href="/dashboard/channels/instagram">{g.openInstagram}</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">{g.backChannels}</SecondaryButton>
          </StepActions>
        </div>
      )}
    </OnboardingShell>
  );
}
