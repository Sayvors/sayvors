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

const STEPS = [
  { key: "start", label: "Get started" },
  { key: "checks", label: "Before you begin" },
  { key: "facebook", label: "Facebook" },
  { key: "pages", label: "Pages" },
  { key: "done", label: "Done" },
];

const STEP_OVERVIEW = 0;
const STEP_CHECKS = 1;
const STEP_FACEBOOK = 2;
const STEP_PAGES = 3;
const STEP_DONE = 4;

const CHECKS = [
  "I am an admin of the Facebook Page I want to connect.",
  "I can log in to the Facebook account that manages that Page right now.",
  "I understand Sayvors will reply to comments and messages on my behalf.",
];

export default function FacebookConnectFlow() {
  const params = useSearchParams();
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
        setError(`Meta rejected the connection (${failure}). Try again.`);
        setStep(STEP_FACEBOOK);
      }
      if (discovery) {
        setError(
          `Connected, but Page discovery failed (Graph ${discovery}). Grant the Page in the Meta dialog and reconnect.`
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
      setError(e instanceof Error ? e.message : "Could not start Facebook connect.");
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
      setError("Could not activate the selected Pages. Try again, or pick them later on the Facebook page.");
    } finally {
      setBusy(false);
    }
  };

  const allChecked = checks.every(Boolean);

  return (
    <OnboardingShell
      platform="facebook"
      title="Connect your Facebook Page"
      subtitle="Let our AI answer comments and Messenger messages on your own Page, and publish posts from the same workspace."
      steps={STEPS}
      current={step}
      onStepClick={(i) => {
        if (i < step) setStep(i);
      }}
      aside={
        step === STEP_OVERVIEW ? (
          <>
            <BenefitList
              title="What you get"
              items={[
                {
                  icon: "💬",
                  label: "Comments handled",
                  body: "The AI replies to comments on your posts in your brand voice.",
                },
                {
                  icon: "✉️",
                  label: "Messenger DMs",
                  body: "Direct messages land in the same inbox your team already watches.",
                },
                {
                  icon: "🗓️",
                  label: "Publish on schedule",
                  body: "Write, schedule and publish Page posts without leaving Sayvors.",
                },
              ]}
            />
            <RequirementList
              items={[
                "A Facebook Page you manage.",
                "Admin access to that Page — editor access cannot grant messaging permissions.",
                "The Facebook login for the account that manages it.",
              ]}
            />
            <GuidelineNote
              title="Connect your Facebook Page"
              lines={[
                "Use your official business Page.",
                "The Page must be published and you must be an admin of it.",
                "Unlink any personal Pages you do not want to share with Sayvors.",
              ]}
            />
          </>
        ) : null
      }
    >
      {step === STEP_OVERVIEW && (
        <div>
          <StepHeading
            title="Connect your own Page"
            body="Sayvors only acts on Pages you explicitly pick. Nothing is published or answered until you choose a Page and turn the features on."
          />

          {alreadyConnected && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] leading-relaxed text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300">
              A Facebook Page is already connected. You can reconnect below, or open the{" "}
              <Link href="/dashboard/channels/facebook" className="font-semibold underline underline-offset-2">
                Facebook page
              </Link>{" "}
              to manage it.
            </p>
          )}

          <ul className="mt-4 space-y-2 text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              Meta shows its own consent screen — Sayvors never sees your Facebook password.
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              You pick which Pages to share on the next screen.
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              You can disconnect at any time without losing conversation history.
            </li>
          </ul>

          <StepActions hint="Takes about 2 minutes.">
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
            body="Confirm these three things — Meta will only grant the permissions an admin can approve."
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
            body="You leave Sayvors for Meta's consent screen, then come straight back here to choose your Page."
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          <StepActions hint="Make sure you are logged in to the account that manages the Page.">
            <PrimaryButton onClick={() => void handleConnect()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> Opening Facebook…
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

      {step === STEP_PAGES && (
        <AssetPicker
          title="Which Pages should Sayvors use?"
          body="These are the Pages Meta shared with us. Pick the ones the AI should answer on — you can change this later."
          emptyText="Meta did not return any Pages for this login. Make sure you granted the Page in the Meta dialog, then reconnect."
          assets={pages}
          picked={picked}
          onToggle={(id) =>
            setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
          }
          onSave={() => void savePages()}
          onBack={() => setStep(STEP_FACEBOOK)}
          busy={busy}
          error={error}
          savedLabel="Only selected Pages are visible in Sayvors."
        />
      )}

      {step === STEP_DONE && (
        <div>
          <StepHeading
            title="Facebook is connected"
            body="Comments, messages and publishing now work for the Pages you selected."
          />
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-500/25 dark:bg-emerald-500/10">
            <p className="text-[12px] font-semibold text-emerald-800 dark:text-emerald-300">
              {picked.length} Page{picked.length === 1 ? "" : "s"} active
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-emerald-800/80 dark:text-emerald-300/80">
              New comments and messages appear in the inbox. Publish from Posts &amp; Media.
            </p>
          </div>
          <StepActions>
            <PrimaryButton href="/dashboard/channels/facebook">Open Facebook</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">Back to channels</SecondaryButton>
          </StepActions>
        </div>
      )}
    </OnboardingShell>
  );
}
