"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import {
  fetchFacebookProfile,
  type FacebookProfile,
  type MetaAsset,
} from "@/lib/api-meta";
import PlatformMark from "@/components/channels/PlatformMark";
import { INK2 } from "../instagram/ui";

/*
 * The tenant's OWN Page — read-only, like Instagram's profile: Meta
 * exposes no profile-write API for Pages, so there is no save button and
 * the honesty line says where to edit instead.
 */

const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";
const FIELD_LABEL = "text-[12px] font-semibold text-[var(--ui-ink-2)]";
const HAIRLINE = "border-b border-[var(--ui-line)] pb-4";

function Row({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <div className={HAIRLINE}>
      <p className={FIELD_LABEL}>{label}</p>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-block text-[13px] text-[var(--ui-ink)] underline underline-offset-2"
        >
          {value}
        </a>
      ) : (
        <p className="mt-1 break-words text-[13px] text-[var(--ui-ink)]">{value}</p>
      )}
    </div>
  );
}

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-4 py-3">
      <p className="text-[20px] font-bold tabular-nums text-[var(--ui-ink)]">
        {value.toLocaleString()}
      </p>
      <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">{label}</p>
    </div>
  );
}

export default function ProfileTab({ asset }: { asset: MetaAsset }) {
  const [profile, setProfile] = useState<FacebookProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Bumping this re-runs the single fetch effect below; the button owns the
  // spinner so a manual refresh never blanks the page.
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Manual refreshes (refreshKey > 0) bypass the server's redis cache —
    // a Refresh button that serves a 5-minute-old copy would be a lie.
    fetchFacebookProfile(
      asset.external_asset_id,
      refreshKey > 0 ? { refresh: true } : undefined
    ).then(
      (data) => {
        if (!cancelled) {
          setProfile(data);
          setError(null);
          setLoading(false);
        }
      },
      (e: unknown) => {
        if (!cancelled) {
          setProfile(null);
          setError(e instanceof Error ? e.message : "Could not load the Page profile.");
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [asset.external_asset_id, refreshKey]);

  const refresh = () => {
    setProfile(null);
    setError(null);
    setLoading(true);
    setRefreshKey((k) => k + 1);
  };

  return (
    <div className="space-y-6">
      <section className={PANEL}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Page</h3>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="ui-btn rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {error && (
          <div
            role="alert"
            className="mt-4 rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4"
          >
            <p className="text-[13px] font-bold text-[var(--ui-ink)]">{error}</p>
            <button
              type="button"
              onClick={refresh}
              className="ui-btn mt-3 rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
            >
              Try again
            </button>
          </div>
        )}

        <div className="mt-5 flex items-start gap-4">
          {profile?.profile_picture_url ? (
            <Image
              src={profile.profile_picture_url}
              alt=""
              width={72}
              height={72}
              className="h-[72px] w-[72px] shrink-0 rounded-full border border-[var(--ui-line)] object-cover"
              unoptimized
            />
          ) : (
            <span
              aria-hidden
              className="flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
            >
              <PlatformMark platform="facebook" size={32} />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-[17px] font-bold text-[var(--ui-ink)]">
              {profile?.name || (loading ? "Loading…" : "Not available")}
            </p>
            <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
              {profile?.link ? "Facebook Page" : "—"}
            </p>
          </div>
        </div>
      </section>

      <section className={PANEL}>
        <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Profile details</h3>
        <p className={`mt-1 text-[12px] ${INK2}`}>
          Facebook does not let apps change these — edit them in Facebook, and Sayvors will
          pick the change up on the next refresh.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Row label="Page" value={profile?.name || "—"} />
          <Row
            label="Open on Facebook"
            value={profile?.link ? "View the live Page" : "—"}
            {...(profile?.link ? { href: profile.link } : {})}
          />
        </div>
      </section>

      {profile && (
        <section className={PANEL}>
          <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Audience</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Counter label="Followers" value={profile.followers_count} />
            <Counter label="Page likes" value={profile.fan_count} />
          </div>
        </section>
      )}
    </div>
  );
}
