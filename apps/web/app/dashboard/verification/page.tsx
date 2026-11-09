"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { apiFetch } from "@/lib/api-rag";
import { GBP_DASHBOARD_URL } from "@/lib/google-links";
import LogoLoader from "@/components/LogoLoader";
import GoogleBusinessLogo from "@/components/channels/GoogleBusinessLogo";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type VerificationDict = Dict["verification"];
type MethodDict = Dict["verification"]["methods"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

function labelFor(method: string | undefined, vm: MethodDict) {
  const known = method ? vm[method as keyof MethodDict] : undefined;
  if (known && typeof known === "object") return known;
  return {
    title: method ? method.replaceAll("_", " ").toLowerCase() : vm.unknownTitle,
    description: vm.unknownDesc,
    timing: "",
  };
}

type Channel = { id: string; display_name: string | null; platform: string; status: string };

type EmailData = { user?: string; domain?: string; isUserNameEditable?: boolean };
type AddressData = {
  business?: string;
  address?: { addressLines?: string[]; locality?: string; administrativeArea?: string; postalCode?: string };
  expectedDeliveryDaysRegion?: number;
};
type VerificationOption = {
  verificationMethod?: string;
  phoneNumber?: string;
  emailData?: EmailData;
  addressData?: AddressData;
  announcement?: string;
};
type VerificationItem = {
  name?: string;
  method?: string;
  state?: "PENDING" | "COMPLETED" | "FAILED" | string;
  createTime?: string;
};
type Verification = {
  channel_id: string;
  status: string;
  method: string | null;
  contact_target: string | null;
  attempts: number;
  requested_at: string | null;
  verified_at: string | null;
  provider_managed: boolean;
  has_voice_of_merchant: boolean | null;
  has_business_authority: boolean | null;
  location_address?: string | null;
  location_country?: string | null;
  location_phone?: string | null;
  location_website?: string | null;
  account_name?: string | null;
  options: VerificationOption[];
  verifications: VerificationItem[];
  provider_name: string | null;
  provider_error: string | null;
};

function optionTarget(option: VerificationOption): string {
  if (option.phoneNumber) return option.phoneNumber;
  const email = option.emailData;
  if (email?.user && email?.domain) return `${email.user}@${email.domain}`;
  const address = option.addressData?.address;
  if (address) {
    return [address.addressLines?.join(" "), address.locality, address.administrativeArea]
      .filter(Boolean)
      .join(", ");
  }
  return option.announcement || "";
}

function statusTone(status: string): string {
  if (status === "verified") return "bg-emerald-100 text-emerald-700";
  if (status === "pending" || status === "required" || status === "under_review") {
    return "bg-amber-100 text-amber-700";
  }
  if (status === "failed" || status === "guidelines" || status === "ownership_conflict") {
    return "bg-rose-100 text-rose-700";
  }
  return "bg-ink/[0.06] text-ink/60";
}

export default function VerificationPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const requestedChannel = searchParams.get("channel") ?? "";
  const nextParam = searchParams.get("next") ?? "";
  // Only same-app dashboard routes: a verification link must never become an
  // open redirect.
  const nextHref = nextParam.startsWith("/dashboard/") ? nextParam : "";
  const [selectedId, setSelectedId] = useState("");
  const [activeMethod, setActiveMethod] = useState<string | null>(null);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [emailAddress, setEmailAddress] = useState("");
  const [mailerContact, setMailerContact] = useState("");
  const [pin, setPin] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const { t, locale } = useI18n();
  const vf: VerificationDict = t.verification;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);

  const channelsQuery = useQuery({
    queryKey: queryKeys.verification.channels(),
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100");
      return ((data.channels ?? []) as Channel[]).filter(
        (channel) => channel.platform === "google_reviews",
      );
    },
  });
  const channels = channelsQuery.data ?? [];

  useEffect(() => {
    if (selectedId || channels.length === 0) return;
    const requested = channels.some((channel) => channel.id === requestedChannel)
      ? requestedChannel
      : channels[0].id;
    setSelectedId(requested);
  }, [channels, requestedChannel, selectedId]);

  const verificationQuery = useQuery({
    queryKey: queryKeys.verification.detail(selectedId),
    queryFn: () => apiFetch(`/api/v1/channels/${selectedId}/verification`),
    enabled: !!selectedId,
  });
  const verification = (verificationQuery.data ?? null) as Verification | null;
  const options = useMemo(() => verification?.options ?? [], [verification?.options]);

  useEffect(() => {
    setActiveMethod(null);
    setPhoneNumber("");
    setEmailAddress("");
    setMailerContact("");
    setPin("");
    setMessage(null);
  }, [selectedId]);

  useEffect(() => {
    if (!activeMethod && options.length > 0) {
      setActiveMethod(options[0].verificationMethod ?? null);
    }
  }, [activeMethod, options]);

  const selectedOption = options.find((option) => option.verificationMethod === activeMethod);
  const verified = verification?.status === "verified";
  const pending = verification?.status === "pending" && !!verification?.provider_name;
  const contactReady =
    activeMethod === "AUTO" ||
    (activeMethod === "ADDRESS" && mailerContact.trim().length > 0) ||
    ((activeMethod === "SMS" || activeMethod === "PHONE_CALL") &&
      Boolean(phoneNumber.trim() || selectedOption?.phoneNumber)) ||
    (activeMethod === "EMAIL" &&
      Boolean(
        emailAddress.trim() ||
          (selectedOption?.emailData?.user && selectedOption?.emailData?.domain),
      ));

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.verification.detail(selectedId) });
  }, [queryClient, selectedId]);

  const requestVerification = useMutation({
    mutationFn: async () => {
      if (!activeMethod) throw new Error(vf.chooseMethodFirst);
      const body: Record<string, string> = { method: activeMethod, language_code: "en" };
      if (activeMethod === "SMS" || activeMethod === "PHONE_CALL") {
        body.phone_number = phoneNumber.trim() || selectedOption?.phoneNumber || "";
      }
      if (activeMethod === "EMAIL") {
        body.email_address = emailAddress.trim();
      }
      if (activeMethod === "ADDRESS") {
        body.mailer_contact = mailerContact.trim();
      }
      return (await apiFetch(`/api/v1/channels/${selectedId}/verification`, {
        method: "POST",
        body: JSON.stringify(body),
      })) as Verification;
    },
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.verification.detail(selectedId), next);
      setPin("");
      setMessage(
        next.status === "verified"
          ? vf.verifiedOk
          : vf.sentPin,
      );
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : vf.startFail);
    },
  });

  const completeVerification = useMutation({
    mutationFn: async () =>
      (await apiFetch(`/api/v1/channels/${selectedId}/verification/complete`, {
        method: "POST",
        body: JSON.stringify({ pin: pin.trim() }),
      })) as Verification,
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.verification.detail(selectedId), next);
      setPin("");
      setMessage(next.status === "verified" ? vf.pinOk : vf.pinReview);
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : vf.pinFail);
    },
  });

  const selected = channels.find((channel) => channel.id === selectedId);
  const loading = channelsQuery.isPending;
  const busy = requestVerification.isPending || completeVerification.isPending;
  const brandStep = verified ? 3 : pending ? 2 : activeMethod ? 1 : 0;
  const brandSteps = [vf.steps.location, vf.steps.method, vf.steps.review, vf.steps.verified];

  return (
    <div className="team-ui h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl space-y-4 p-3 sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[var(--ui-ink-2)]">
              <GoogleBusinessLogo size={20} />
              <span className="text-[10px] font-bold uppercase tracking-[0.16em]">
                {vf.eyebrow}
              </span>
            </div>
            <h1 className="mt-1 text-[20px] font-bold tracking-tight text-[var(--ui-ink)] sm:text-[24px]">
              {vf.title}
            </h1>
            <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-[var(--ui-ink-2)] sm:text-[13px]">
              {vf.sub}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-wide ${channels.length ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"}`}>
              {channels.length ? vf.connectedBadge : vf.notConnectedBadge}
            </span>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={!selectedId || verificationQuery.isFetching}
              className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3.5 py-2 text-[12px] font-bold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] active:translate-y-px disabled:opacity-40"
            >
              {verificationQuery.isFetching ? vf.refreshing : vf.refresh}
            </button>
          </div>
        </div>

        {message && (
          <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3 text-[12px] text-[var(--ui-ink-2)]">
            {message}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] py-24"><LogoLoader size={34} /></div>
        ) : channels.length === 0 ? (
          <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-5 sm:p-6">
            <div className="flex items-center gap-3">
              <GoogleBusinessLogo size={32} />
              <div>
                <h2 className="text-[16px] font-bold text-[var(--ui-ink)]">{vf.noConnectTitle}</h2>
                <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">{vf.noConnectBody}</p>
              </div>
            </div>
            <p className="mt-3 max-w-2xl text-[12.5px] leading-relaxed text-[var(--ui-ink-2)]">
              {vf.noConnectHint}
            </p>
          </section>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { label: vf.statLocations, value: fmt(channels.length) },
                { label: vf.statSelected, value: selected?.display_name || "—" },
                { label: "Status", value: (verification?.status ?? "unstarted").replaceAll("_", " ") },
                { label: vf.statMethods, value: fmt(options.length) },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2.5">
                  <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">{item.label}</p>
                  <p className="mt-1 truncate text-[13px] font-bold capitalize text-[var(--ui-ink)]">{item.value}</p>
                </div>
              ))}
            </div>

            <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 sm:p-5">
              <div className="flex items-center gap-2">
                <GoogleBusinessLogo size={16} />
                <label className="block text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]" htmlFor="verification-location">
                  {vf.bizLocLabel}
                </label>
              </div>
              <select
                id="verification-location"
                value={selectedId}
                onChange={(event) => setSelectedId(event.target.value)}
                className="mt-2 h-10 w-full rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 text-[12px] font-semibold text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
              >
                <option value="">{vf.noSelection}</option>
                {channels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.display_name || vf.unnamed}
                  </option>
                ))}
              </select>
            </section>

            <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 sm:p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-[16px] font-bold text-ink">{vf.statusTitle}</h2>
                  <p className="mt-1 text-[11px] text-ink/45">
                    {selected?.display_name || vf.noData}
                  </p>
                </div>
                <span className={`rounded-full px-3 py-1 text-[10px] font-bold capitalize ${statusTone(verification?.status ?? "unstarted")}`}>
                  {(verification?.status ?? "unstarted").replaceAll("_", " ")}
                </span>
              </div>

              <div className="mt-4 flex items-center gap-1.5">
                {brandSteps.map((label, index) => (
                  <div key={label} className={`flex items-center gap-1.5 ${index < brandSteps.length - 1 ? "flex-1" : ""}`}>
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold ${
                        index <= brandStep
                          ? "bg-deep-violet text-white"
                          : "bg-ink/[0.06] text-ink/35 dark:bg-fog/[0.08] dark:text-fog/35"
                      }`}
                    >
                      {index < brandStep ? "✓" : index + 1}
                    </span>
                    <span className={`hidden text-[9px] font-bold uppercase tracking-wide sm:block ${index <= brandStep ? "text-[var(--ui-ink)] dark:text-fog/70" : "text-ink/35 dark:text-fog/35"}`}>
                      {label}
                    </span>
                    {index < brandSteps.length - 1 && (
                      <span className={`h-px flex-1 ${index < brandStep ? "bg-deep-violet/30" : "bg-ink/10 dark:bg-fog/10"}`} />
                    )}
                  </div>
                ))}
              </div>

              {verificationQuery.isError && (
                <p className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
                  {verificationQuery.error instanceof Error
                    ? verificationQuery.error.message
                    : vf.loadStatusFail}
                </p>
              )}
              {verification?.provider_error && (
                <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
                  {verification.provider_error}
                </p>
              )}

              <div className="mt-4 rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--ui-ink-2)]">
                  {vf.dataTitle}
                </p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <Info label={vf.addrLabel} value={verification?.location_address ?? ""} />
                  <Info label={vf.countryLabel} value={verification?.location_country ?? ""} />
                  <Info label={vf.phoneLabel} value={verification?.location_phone ?? ""} />
                  <Info label={vf.websiteLabel} value={verification?.location_website ?? ""} />
                  <Info label={vf.accountLabel} value={verification?.account_name ?? ""} />
                </div>
                {verification &&
                  !verification.location_phone &&
                  !verification.location_website && (
                    <p className="mt-2 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
                      {vf.noContactWarn}
                    </p>
                  )}
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <Info
                  label={vf.voiceLabel}
                  value={
                    verification?.has_voice_of_merchant == null
                      ? ""
                      : verification.has_voice_of_merchant
                        ? vf.yesWord
                        : vf.noWord
                  }
                />
                <Info
                  label={vf.lastMethod}
                  value={verification?.method ? labelFor(verification.method, vf.methods).title : ""}
                />
                <Info
                  label={vf.lastRequest}
                  value={
                    verification?.requested_at
                      ? new Date(verification.requested_at).toLocaleDateString(dateLocale)
                      : ""
                  }
                />
              </div>

              {verified && (
                <div className="mt-4 rounded-xl bg-emerald-50 px-4 py-3 text-[12.5px] text-emerald-800">
                  <p>{vf.verifiedNote}</p>
                  {nextHref && (
                    <Link
                      href={nextHref}
                      className="mt-3 flex w-full items-center justify-center rounded-xl bg-deep-violet px-3 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 active:translate-y-px"
                    >
                      {vf.continueSetup}
                    </Link>
                  )}
                </div>
              )}
              {!verified && nextHref && (
                <Link
                  href={nextHref}
                  className="mt-4 inline-flex text-[12px] font-bold text-deep-violet underline underline-offset-2"
                >
                  {vf.setupWhile}
                </Link>
              )}
            </section>

            {!verified && options.length > 0 && (
              <section>
                <div className="mb-3">
                  <h2 className="text-[16px] font-bold text-ink">{vf.methodTitle}</h2>
                  <p className="mt-1 text-[12px] text-ink/45">
                    {vf.methodSub}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {options.map((option) => {
                    const method = option.verificationMethod ?? "";
                    return (
                      <MethodCard
                        key={method}
                        method={method}
                        target={optionTarget(option)}
                        selected={activeMethod === method}
                        disabled={busy}
                        onClick={() => setActiveMethod(method)}
                      />
                    );
                  })}
                </div>
              </section>
            )}

            {!verified && options.length === 0 && (
              <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-5 sm:p-6">
                <h2 className="text-[16px] font-bold text-ink">{vf.needGbpTitle}</h2>
                <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-ink/55">
                  {vf.needGbpBody}
                </p>
                <a
                  href={GBP_DASHBOARD_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-4 inline-flex rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3.5 py-2 text-[12px] font-bold text-deep-violet shadow-sm transition active:translate-y-[2px] active:scale-[0.98]"
                >
                  {vf.openGbp}
                </a>
              </section>
            )}

            {!verified && options.length > 0 && (
              <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 sm:p-5">
                <h2 className="text-[16px] font-bold text-ink">{vf.reqTitle}</h2>
                <p className="mt-1 text-[12px] text-ink/45">
                  {activeMethod ? labelFor(activeMethod, vf.methods).description : vf.selectMethod}
                </p>

                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {activeMethod === "SMS" || activeMethod === "PHONE_CALL" ? (
                    <Field
                      label={vf.phoneField}
                      value={phoneNumber}
                      onChange={setPhoneNumber}
                      placeholder={selectedOption?.phoneNumber || vf.phonePh}
                    />
                  ) : null}
                  {activeMethod === "EMAIL" ? (
                    <Field
                      label={vf.emailLabel}
                      value={emailAddress}
                      onChange={setEmailAddress}
                      placeholder={
                        selectedOption?.emailData?.user && selectedOption?.emailData?.domain
                          ? `${selectedOption.emailData.user}@${selectedOption.emailData.domain}`
                          : vf.emailPh
                      }
                    />
                  ) : null}
                  {activeMethod === "ADDRESS" ? (
                    <Field
                      label={vf.contactLabel}
                      value={mailerContact}
                      onChange={setMailerContact}
                      placeholder={vf.contactPh}
                    />
                  ) : null}
                </div>

                <button
                  type="button"
                  onClick={() => requestVerification.mutate()}
                  disabled={!selectedId || !activeMethod || !contactReady || busy}
                  className="mt-5 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-sm transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {requestVerification.isPending ? vf.starting : vf.startBtn}
                </button>
              </section>
            )}

            {pending && (
              <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 sm:p-5">
                <h2 className="text-[16px] font-bold text-ink">{vf.pinTitle}</h2>
                <p className="mt-1 text-[12px] text-ink/45">
                  {fill(vf.pinSub, { method: labelFor(verification?.method ?? undefined, vf.methods).title.toLowerCase() })}
                </p>
                <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
                  <Field label={vf.pinLabel} value={pin} onChange={setPin} placeholder={vf.pinPh} />
                  <button
                    type="button"
                    onClick={() => completeVerification.mutate()}
                    disabled={!pin.trim() || busy}
                    className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-sm transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {completeVerification.isPending ? vf.submitting : vf.completeBtn}
                  </button>
                </div>
              </section>
            )}

            {verification?.verifications && verification.verifications.length > 0 && (
              <section className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 sm:p-5">
                <h2 className="text-[16px] font-bold text-ink">{vf.histTitle}</h2>
                <ul className="mt-3 divide-y divide-ink/[0.06]">
                  {verification.verifications.map((item) => (
                    <li key={item.name} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[12px]">
                      <span className="font-semibold text-ink/75">
                        {labelFor(item.method, vf.methods).title}
                      </span>
                      <span className="text-ink/45">
                        {item.createTime ? new Date(item.createTime).toLocaleDateString(dateLocale) : ""}
                      </span>
                      <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${statusTone(String(item.state).toLowerCase() === "completed" ? "verified" : String(item.state).toLowerCase())}`}>
                        {String(item.state || "").toLowerCase()}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MethodCard({
  method,
  target,
  selected,
  disabled,
  onClick,
}: {
  method: string;
  target: string;
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  const { t } = useI18n();
  const label = labelFor(method, t.verification.methods);
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-xl border p-4 text-left transition ${
        selected
          ? "border-deep-violet bg-deep-violet/[0.05]"
          : "border-[var(--ui-line)] bg-white hover:border-deep-violet/25"
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[13px] font-bold text-ink">{label.title}</div>
          <div className="mt-1 text-[11px] leading-relaxed text-ink/50">{label.description}</div>
          {target && <div className="mt-2 text-[10.5px] font-semibold text-ink/45">{target}</div>}
        </div>
        {label.timing && (
          <span className="rounded-full bg-ink/[0.05] px-2 py-1 text-[9px] font-bold text-ink/45">
            {label.timing}
          </span>
        )}
      </div>
      <div className={`mt-4 h-1 rounded-full ${selected ? "bg-deep-violet" : "bg-ink/[0.06]"}`} />
    </button>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="text-[11px] font-bold text-ink/55">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="input-field mt-1"
      />
    </label>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3">
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--ui-ink-2)]">{label}</div>
      <div className="mt-2 min-h-4 text-[12px] font-medium text-[var(--ui-ink)]">{value || " "}</div>
    </div>
  );
}
