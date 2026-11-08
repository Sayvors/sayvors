"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
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
 * Facebook onboarding.
 *
 * The OAuth hand-off leaves the app, so the screen has to pick the flow back
 * up when Meta redirects to /dashboard/channels/facebook/connect with
 * meta_connected=facebook. That return path is recorded in the OAuth
 * transaction by the backend — not guessed here.
 */

const STEP_OVERVIEW = 0;
const STEP_CHECKS = 1;
const STEP_FACEBOOK = 2;
const STEP_PAGES = 3;
const STEP_DONE = 4;

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

export default function FacebookConnectFlow() {
  const params = useSearchParams();
  const { t } = useI18n();
  const f = t.dashboard.connect.facebook;
  const STEPS = [
    { key: "start", label: f.steps.start },
    { key: "checks", label: f.steps.checks },
    { key: "facebook", label: f.steps.facebook },
    { key: "pages", label: f.steps.pages },
    { key: "done", label: f.steps.done },
  ];
  const CHECKS = [...f.checks];
  const [step, setStep] = useState(STEP_OVERVIEW);
  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alreadyConnected, setAlreadyConnected] = useState(false);
  const [pages, setPages] = useState<MetaAsset[]>([]);
  const [picked, setPicked] = useState<string[]>([]);

  const loadPages = useCallback(async () => {
    try {
      const r = await fetchMetaAssets("facebook");
      const list = (r.assets ?? []).filter((a) => a.asset_type === "page");
      setPages(list);
      setPicked(list.filter((a) => a.active).map((a) => a.id));
    } catch {
      setPages([]);
    }
  }, []);

  useEffect(() => {
    warmFacebookSdk();
    let cancelled = false;
    (async () => {
      const connected = params.get("meta_connected");
      const failure = params.get("meta_error");
      const discovery = params.get("discovery_error");

      if (connected || failure || discovery) {
        // Strip the OAuth result so a refresh never replays it.
        try {
          window.history.replaceState(null, "", window.location.pathname);
        } catch {
          /* keep params — worst case a refresh re-opens the picker */
        }
      }

      if (failure) {
        setError(fill(f.errors.rejected, { code: failure }));
        setStep(STEP_FACEBOOK);
      }
      if (discovery) {
        setError(
          fill(f.errors.discovery, { code: discovery }),
        );
        setStep(STEP_PAGES);
      }
      if (connected === "facebook" && !discovery) {
        await loadPages();
        if (cancelled) return;
        setAlreadyConnected(true);
        setStep(STEP_PAGES);
        return;
      }

      try {
        const conns = await fetchMetaConnections();
        if (cancelled) return;
        const fb = (conns.connections ?? []).find((c) => c.provider === "facebook");
        setAlreadyConnected(Boolean(fb && fb.status !== "revoked"));
        await loadPages();
      } catch {
        /* backend down — the flow still explains itself */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params, loadPages]);

  const handleConnect = async () => {
    setBusy(true);
    setError(null);
    try {
      await startMetaOAuth("facebook", "/dashboard/channels/facebook/connect");
    } catch (e) {
      setError(e instanceof Error ? e.message : f.errors.start);
      setBusy(false);
    }
  };

  const savePages = async () => {
    setBusy(true);
    setError(null);
    try {
      await selectMetaAssets("facebook", picked);
      setStep(STEP_DONE);
    } catch {
      setError(f.errors.save);
    } finally {
      setBusy(false);
    }
  };

  const allChecked = checks.every(Boolean);

  return (
    <OnboardingShell
      platform="facebook"
      title={f.title}
      subtitle={f.subtitle}
      steps={STEPS}
      current={step}
      onStepClick={(i) => {
        if (i < step) setStep(i);
      }}
      aside={
        step === STEP_OVERVIEW ? (
          <>
            <BenefitList
              title={f.benefitsTitle}
              items={f.benefits.map((b, i) => ({ icon: ["💬", "✉️", "🗓️"][i], label: b.label, body: b.body }))}
            />
            <RequirementList
              items={[...f.requirements]}
            />
            <GuidelineNote
              title={f.guidelineTitle}
              lines={[...f.guideline]}
            />
          </>
        ) : null
      }
    >
      {step === STEP_OVERVIEW && (
        <div>
          <StepHeading
            title={f.overviewTitle}
            body={f.overviewBody}
          />

          {alreadyConnected && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] leading-relaxed text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300">
              {f.already}{" "}
              <Link href="/dashboard/channels/facebook" className="font-semibold underline underline-offset-2">
                {f.alreadyLink}
              </Link>{" "}
              {f.alreadyTail}
            </p>
          )}

          <ul className="mt-4 space-y-2 text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {f.bullets[0]}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {f.bullets[1]}
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              {f.bullets[2]}
            </li>
          </ul>

          <StepActions hint={f.overviewHint}>
            <PrimaryButton onClick={() => setStep(STEP_CHECKS)}>{t.dashboard.connect.continue}</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">{t.common.cancel}</SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_CHECKS && (
        <div>
          <StepHeading
            eyebrow={f.stepOne}
            title={f.checksTitle}
            body={f.checksBody}
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
          <StepActions hint={f.checksHint}>
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
            eyebrow={f.stepTwo}
            title={f.fbTitle}
            body={f.fbBody}
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          <StepActions hint={f.fbHint}>
            <PrimaryButton onClick={() => void handleConnect()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> {f.opening}
                </span>
              ) : (
                f.fbTitle
              )}
            </PrimaryButton>
            <SecondaryButton onClick={() => setStep(STEP_CHECKS)} disabled={busy}>
              {t.common.back}
            </SecondaryButton>
          </StepActions>
        </div>
      )}

      {step === STEP_PAGES && (
        <AssetPicker
          eyebrow={f.pagesEyebrow}
          title={f.pagesTitle}
          body={f.pagesBody}
          emptyText={f.pagesEmpty}
          assets={pages}
          picked={picked}
          onToggle={(id) =>
            setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
          }
          onSave={() => void savePages()}
          onBack={() => setStep(STEP_FACEBOOK)}
          busy={busy}
          error={error}
          savedLabel={f.pagesSaved}
        />
      )}

      {step === STEP_DONE && (
        <div>
          <StepHeading
            title={f.doneTitle}
            body={f.doneBody}
          />
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-500/25 dark:bg-emerald-500/10">
            <p className="text-[12px] font-semibold text-emerald-800 dark:text-emerald-300">
              {fill(f.activeN, { count: picked.length })}
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-emerald-800/80 dark:text-emerald-300/80">
              {f.doneDetail}
            </p>
          </div>
          <StepActions>
            <PrimaryButton href="/dashboard/channels/facebook">{f.openFacebook}</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">{f.backChannels}</SecondaryButton>
          </StepActions>
        </div>
      )}
    </OnboardingShell>
  );
}
