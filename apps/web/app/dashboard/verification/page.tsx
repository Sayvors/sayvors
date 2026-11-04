"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

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
  options: VerificationOption[];
  verifications: VerificationItem[];
  provider_name: string | null;
  provider_error: string | null;
};

const METHOD_LABELS: Record<string, { title: string; description: string; timing: string }> = {
  ADDRESS: { title: "Postcard", description: "Mail a PIN to the business address on file.", timing: "5-14 days" },
  PHONE_CALL: { title: "Phone call", description: "Google calls the eligible business number with a PIN.", timing: "Instant" },
  SMS: { title: "SMS", description: "Google texts a PIN to the eligible business number.", timing: "Instant" },
  EMAIL: { title: "Email", description: "Google emails a PIN to an eligible business address.", timing: "Instant" },
  AUTO: { title: "Instant", description: "Google can verify this location without more action.", timing: "Instant" },
  TRUSTED_PARTNER: { title: "Partner", description: "Verify through Google's trusted partner flow.", timing: "Partner" },
};

function labelFor(method: string | undefined) {
  return (method && METHOD_LABELS[method]) || {
    title: method ? method.replaceAll("_", " ").toLowerCase() : "Verification",
    description: "Use the method Google returned for this location.",
    timing: "",
  };
}

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
  const [selectedId, setSelectedId] = useState("");
  const [activeMethod, setActiveMethod] = useState<string | null>(null);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [emailAddress, setEmailAddress] = useState("");
  const [mailerContact, setMailerContact] = useState("");
  const [pin, setPin] = useState("");
  const [message, setMessage] = useState<string | null>(null);

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
    if (!selectedId && channels.length > 0) setSelectedId(channels[0].id);
  }, [channels, selectedId]);

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
      if (!activeMethod) throw new Error("Choose a verification method first.");
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
          ? "Google verified this location."
          : "Google sent the verification request. Enter the PIN below when it arrives.",
      );
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "Google could not start verification.");
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
      setMessage(next.status === "verified" ? "Verification complete." : "PIN submitted; Google is still reviewing the location.");
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "Google could not complete verification.");
    },
  });

  const selected = channels.find((channel) => channel.id === selectedId);
  const loading = channelsQuery.isPending;
  const busy = requestVerification.isPending || completeVerification.isPending;

  return (
    <div className="h-full overflow-y-auto bg-[#f1f2f5] p-4 sm:p-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-[22px] font-bold text-ink dark:text-fog">Verification</h1>
            <p className="mt-1 text-[13px] text-ink/55 dark:text-fog/55">
              Google Business Profile verification, live from the My Business Verifications API.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${channels.length ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
              {channels.length ? "Google connected" : "Google not connected"}
            </span>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={!selectedId || verificationQuery.isFetching}
              className="rounded-[24px] border border-ink/10 bg-white px-3.5 py-2 text-[12px] font-bold text-ink/70 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_4px_12px_rgba(20,16,31,0.06)] transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-40"
            >
              {verificationQuery.isFetching ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>

        {message && (
          <div className="rounded-[20px] border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">
            {message}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center rounded-[32px] bg-white py-24"><LogoLoader size={34} /></div>
        ) : channels.length === 0 ? (
          <section className="rounded-[32px] bg-white p-6 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
            <h2 className="text-[16px] font-bold text-ink">Connect Google first</h2>
            <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-ink/55">
              Verification is available only for a location connected through Google Business Profile OAuth.
            </p>
          </section>
        ) : (
          <>
            <section className="rounded-[32px] bg-white p-5 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
              <label className="block text-[11px] font-bold text-ink/55" htmlFor="verification-location">
                Business location
              </label>
              <select
                id="verification-location"
                value={selectedId}
                onChange={(event) => setSelectedId(event.target.value)}
                className="input-field mt-2"
              >
                <option value="">No location selected</option>
                {channels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.display_name || "Unnamed location"}
                  </option>
                ))}
              </select>
            </section>

            <section className="rounded-[32px] bg-white p-5 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-[16px] font-bold text-ink">Verification status</h2>
                  <p className="mt-1 text-[11px] text-ink/45">
                    {selected?.display_name || "No connected location data"}
                  </p>
                </div>
                <span className={`rounded-full px-3 py-1 text-[10px] font-bold capitalize ${statusTone(verification?.status ?? "unstarted")}`}>
                  {(verification?.status ?? "unstarted").replaceAll("_", " ")}
                </span>
              </div>

              {verificationQuery.isError && (
                <p className="mt-4 rounded-[20px] bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
                  {verificationQuery.error instanceof Error
                    ? verificationQuery.error.message
                    : "Could not read verification status from Google."}
                </p>
              )}
              {verification?.provider_error && (
                <p className="mt-4 rounded-[20px] bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
                  {verification.provider_error}
                </p>
              )}

              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <Info
                  label="Voice of Merchant"
                  value={
                    verification?.has_voice_of_merchant == null
                      ? ""
                      : verification.has_voice_of_merchant
                        ? "Yes"
                        : "No"
                  }
                />
                <Info
                  label="Method"
                  value={verification?.method ? labelFor(verification.method).title : ""}
                />
                <Info
                  label="Last request"
                  value={
                    verification?.requested_at
                      ? new Date(verification.requested_at).toLocaleDateString()
                      : ""
                  }
                />
              </div>

              {verified && (
                <div className="mt-4 rounded-[24px] bg-emerald-50 px-4 py-3 text-[12.5px] text-emerald-800">
                  Google already considers this location verified. No further action is needed.
                </div>
              )}
            </section>

            {!verified && options.length > 0 && (
              <section>
                <div className="mb-3">
                  <h2 className="text-[16px] font-bold text-ink">Choose a verification method</h2>
                  <p className="mt-1 text-[12px] text-ink/45">
                    These are the methods Google currently offers for this location.
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
              <section className="rounded-[32px] bg-white p-6 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
                <h2 className="text-[16px] font-bold text-ink">No eligible methods returned</h2>
                <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-ink/55">
                  Google did not return a verification method for this location. It may already be
                  verified, under review, or require action in the Google Business Profile dashboard.
                </p>
              </section>
            )}

            {!verified && options.length > 0 && (
              <section className="rounded-[32px] bg-white p-5 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
                <h2 className="text-[16px] font-bold text-ink">Request details</h2>
                <p className="mt-1 text-[12px] text-ink/45">
                  {activeMethod ? labelFor(activeMethod).description : "Select a method above."}
                </p>

                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {(activeMethod === "SMS" || activeMethod === "PHONE_CALL") && (
                    <Field
                      label="Phone number"
                      value={phoneNumber}
                      onChange={setPhoneNumber}
                      placeholder={selectedOption?.phoneNumber || "Number Google returned"}
                    />
                  )}
                  {activeMethod === "EMAIL" && (
                    <Field
                      label="Email address"
                      value={emailAddress}
                      onChange={setEmailAddress}
                      placeholder={
                        selectedOption?.emailData?.user && selectedOption?.emailData?.domain
                          ? `${selectedOption.emailData.user}@${selectedOption.emailData.domain}`
                          : "Address Google returned"
                      }
                    />
                  )}
                  {activeMethod === "ADDRESS" && (
                    <Field
                      label="Contact name"
                      value={mailerContact}
                      onChange={setMailerContact}
                      placeholder="Name on the postcard"
                    />
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => requestVerification.mutate()}
                  disabled={!selectedId || !activeMethod || !contactReady || busy}
                  className="mt-5 rounded-[24px] bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-[0_1px_0_rgba(255,255,255,0.18)_inset,0_6px_16px_rgba(61,29,110,0.22)] transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {requestVerification.isPending ? "Starting..." : "Start verification"}
                </button>
              </section>
            )}

            {pending && (
              <section className="rounded-[32px] bg-white p-5 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
                <h2 className="text-[16px] font-bold text-ink">Enter the PIN</h2>
                <p className="mt-1 text-[12px] text-ink/45">
                  Google is waiting for the code it sent through {labelFor(verification?.method ?? undefined).title.toLowerCase()}.
                </p>
                <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
                  <Field label="Verification PIN" value={pin} onChange={setPin} placeholder="Code from Google" />
                  <button
                    type="button"
                    onClick={() => completeVerification.mutate()}
                    disabled={!pin.trim() || busy}
                    className="rounded-[24px] bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-[0_1px_0_rgba(255,255,255,0.18)_inset,0_6px_16px_rgba(61,29,110,0.22)] transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {completeVerification.isPending ? "Submitting..." : "Complete verification"}
                  </button>
                </div>
              </section>
            )}

            {verification?.verifications && verification.verifications.length > 0 && (
              <section className="rounded-[32px] bg-white p-5 shadow-[0_12px_30px_rgba(20,16,31,0.07)]">
                <h2 className="text-[16px] font-bold text-ink">Google verification history</h2>
                <ul className="mt-3 divide-y divide-ink/[0.06]">
                  {verification.verifications.map((item) => (
                    <li key={item.name} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[12px]">
                      <span className="font-semibold text-ink/75">
                        {labelFor(item.method).title}
                      </span>
                      <span className="text-ink/45">
                        {item.createTime ? new Date(item.createTime).toLocaleDateString() : ""}
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
  const label = labelFor(method);
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-[24px] border p-4 text-left transition ${
        selected
          ? "border-deep-violet bg-deep-violet/[0.05]"
          : "border-black/[0.06] bg-white hover:border-deep-violet/25"
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
    <div className="rounded-[20px] bg-ink/[0.03] p-3">
      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{label}</div>
      <div className="mt-2 min-h-4 text-[12px] text-ink/70">{value || " "}</div>
    </div>
  );
}
