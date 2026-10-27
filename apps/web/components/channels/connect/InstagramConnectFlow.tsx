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

const STEPS = [
  { key: "start", label: "Get started" },
  { key: "checks", label: "Before you begin" },
  { key: "facebook", label: "Facebook" },
  { key: "accounts", label: "Accounts" },
  { key: "done", label: "Done" },
];

const STEP_OVERVIEW = 0;
const STEP_CHECKS = 1;
const STEP_FACEBOOK = 2;
const STEP_ACCOUNTS = 3;
const STEP_DONE = 4;

const CHECKS = [
  "My Instagram account is a professional (Business or Creator) account.",
  "That Instagram account is linked to a Facebook Page I am an admin of.",
  "I can log in to the Facebook account that manages that Page.",
];

export default function InstagramConnectFlow() {
  const params = useSearchParams();
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
        setError(
          "No Instagram professional accounts were found. Link your Instagram account to the Facebook Page, then try again."
        );
      }
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not discover Instagram accounts. Connect Facebook first, then retry."
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
        setError(`Meta rejected the connection (${failure}). Try again.`);
        setStep(STEP_FACEBOOK);
      }
      if (discovery) {
        setError(
          `Connected, but Page discovery failed (Graph ${discovery}). Grant the Page in the Meta dialog and reconnect.`
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
      setError(e instanceof Error ? e.message : "Could not start Instagram connect.");
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
      setError("Could not activate the selected account. Try again, or pick it later on the Instagram page.");
    } finally {
      setBusy(false);
    }
  };

  const allChecked = checks.every(Boolean);

  return (
    <OnboardingShell
      platform="instagram"
      title="Connect Instagram"
      subtitle="Answer comments and DMs on your Instagram professional account — through the Facebook Page it is linked to."
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
                  label: "Comment replies",
                  body: "The AI answers comments on your posts and reels in your brand voice.",
                },
                {
                  icon: "✉️",
                  label: "DM inbox",
                  body: "Instagram direct messages land in the same inbox as WhatsApp and Facebook.",
                },
                {
                  icon: "📊",
                  label: "Post insights",
                  body: "See reach, saves and shares for every post you publish.",
                },
              ]}
            />
            <RequirementList
              items={[
                "An Instagram Business or Creator account.",
                "That account linked to a Facebook Page you manage.",
                "Admin access to the Page — editor access cannot grant messaging permissions.",
              ]}
            />
            <GuidelineNote
              title="Connect your Instagram Account"
              lines={[
                "Use your official business account.",
                "The account must be a Business or Creator account linked to a Facebook Page.",
                "Unlink any personal accounts you do not want to share with Sayvors.",
              ]}
            />
          </>
        ) : null
      }
    >
      {step === STEP_OVERVIEW && (
        <div>
          <StepHeading
            title="Connect your professional account"
            body="Instagram does not have its own login here: Meta grants access through the Facebook Page your account is linked to. That is why the next step asks for Facebook."
          />

          {alreadyConnected && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] leading-relaxed text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-300">
              Instagram is already connected. You can reconnect below, or open the{" "}
              <Link href="/dashboard/channels/instagram" className="font-semibold underline underline-offset-2">
                Instagram page
              </Link>{" "}
              to manage it.
            </p>
          )}

          <ul className="mt-4 space-y-2 text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              If your account is still personal, switch it to Business or Creator in the Instagram app first.
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              Link the Instagram account to your Facebook Page in Meta Business Suite.
            </li>
            <li className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
              Then come back here and continue with Facebook.
            </li>
          </ul>

          <StepActions hint="Takes about 3 minutes.">
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
            body="All three must be true. Meta only returns Instagram accounts that are linked to a Page you administer."
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
            body="Meta will ask which Pages to share. Instagram access is granted through that Page, then you come back here to pick the account."
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

      {step === STEP_ACCOUNTS && (
        <div>
          <StepHeading
            eyebrow="Almost there"
            title="Which Instagram account should Sayvors use?"
            body="We look for professional accounts linked to the Pages you just shared. Pick the one the AI should answer on."
          />

          {error && <ErrorNote>{error}</ErrorNote>}

          <div className="mt-4">
            <SecondaryButton onClick={() => void discover()} disabled={busy}>
              {busy ? (
                <span className="inline-flex items-center gap-2">
                  <LogoLoader size={14} /> Looking for accounts…
                </span>
              ) : (
                "Discover accounts again"
              )}
            </SecondaryButton>
          </div>

          <div className="mt-4">
            <AssetPicker
              eyebrow="Accounts"
              title="Discovered accounts"
              body="Only accounts linked to a Page you administer can appear here."
              emptyText="No Instagram account discovered yet. Use the button above after checking the Page link in Meta Business Suite."
              assets={accounts}
              picked={picked}
              onToggle={(id) =>
                setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
              }
              onSave={() => void saveAccounts()}
              onBack={() => setStep(STEP_FACEBOOK)}
              busy={busy}
              error={null}
              savedLabel="Only selected accounts are visible in Sayvors."
            />
          </div>
        </div>
      )}

      {step === STEP_DONE && (
        <div>
          <StepHeading
            title="Instagram is connected"
            body="Comments and DMs on the selected account now flow into Sayvors."
          />
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-500/25 dark:bg-emerald-500/10">
            <p className="text-[12px] font-semibold text-emerald-800 dark:text-emerald-300">
              {picked.length} account{picked.length === 1 ? "" : "s"} active
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-emerald-800/80 dark:text-emerald-300/80">
              New comments and DMs appear in the inbox. Posting and insights live on the Instagram page.
            </p>
          </div>
          <StepActions>
            <PrimaryButton href="/dashboard/channels/instagram">Open Instagram</PrimaryButton>
            <SecondaryButton href="/dashboard/channels">Back to channels</SecondaryButton>
          </StepActions>
        </div>
      )}
    </OnboardingShell>
  );
}
