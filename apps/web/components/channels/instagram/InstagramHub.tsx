"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import {
  fetchInstagramProfile,
  fetchMetaAssets,
  type InstagramProfile,
  type MetaAsset,
} from "@/lib/api-meta";
import PlatformMark from "@/components/channels/PlatformMark";
import AudienceTab from "./AudienceTab";
import CommentsTab from "./CommentsTab";
import PostComposer from "./PostComposer";
import PostsGrid from "./PostsGrid";
import StoriesStrip from "./StoriesStrip";
import { MessagesTab } from "./ListsTab";

/*
 * Instagram hub.
 *
 * Tabs are the shell the rest of Instagram slots into; only Profile is live
 * today. Nothing here is editable on purpose: Meta's IG User reference states
 * updating a profile is not supported, so a save button would only ever 400 and
 * lose the tenant's edits. Sayvors-side overrides are the honest alternative
 * and are a separate feature.
 *
 * Design: the locked three-colour system (#000 ink, #FFF surfaces, #F5F5F5
 * page), hairlines for depth, no gradients and no blur.
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";

const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";
const FIELD_LABEL = "text-[12px] font-semibold text-[var(--ui-ink-2)]";
const VALUE = "mt-1 text-[13px] text-[var(--ui-ink)]";
const HAIRLINE = "border-b border-[var(--ui-line)] pb-4";

type Tab = "profile" | "audience" | "messages" | "posts" | "comments";

const TABS: { key: Tab; label: string; live: boolean }[] = [
  { key: "profile", label: "Profile", live: true },
  { key: "audience", label: "Audience", live: true },
  { key: "messages", label: "Messages", live: true },
  { key: "posts", label: "Posts", live: true },
  { key: "comments", label: "Comments", live: true },
];

function Row({ label, value, href }: { label: string; value: string; href?: string }) {
  return (
    <div className={HAIRLINE}>
      <p className={FIELD_LABEL}>{label}</p>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className={`mt-1 inline-block text-[13px] text-[var(--ui-ink)] underline underline-offset-2`}
        >
          {value}
        </a>
      ) : (
        <p className={`${VALUE} break-words`}>{value}</p>
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

function ProfileTab({ asset }: { asset: MetaAsset }) {
  const [profile, setProfile] = useState<InstagramProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Bumping this re-runs the single fetch effect below; the button owns the
  // spinner so a manual refresh never blanks the page.
  const [refreshKey, setRefreshKey] = useState(0);

  // One fetch, owned by the effect with a cancel flag — the same shape the
  // dashboard sidebar uses. No state changes synchronously during mount.
  useEffect(() => {
    let cancelled = false;
    // Manual refreshes (refreshKey > 0) bypass the server's redis cache —
    // a Refresh button that serves a 5-minute-old copy would be a lie.
    fetchInstagramProfile(
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
          setError(e instanceof Error ? e.message : "Could not load the Instagram profile.");
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

  const handle = profile?.username ? `https://instagram.com/${profile.username}` : undefined;

  return (
    <div className="space-y-6">
      <section className={PANEL}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Account</h3>
          <div className="flex items-center gap-2">
            {profile?.stale && (
              <span className="rounded-[8px] bg-[var(--ui-ink)] px-3 py-1 text-[12px] font-bold text-[var(--ui-on-ink)]">
                Cached copy
              </span>
            )}
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="ui-btn rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
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

        {profile?.stale && !error && (
          <p className="mt-4 rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink-2)]">
            Instagram could not be reached, so this is the last copy we saved.
            {profile.synced_at ? ` Saved ${new Date(profile.synced_at).toLocaleString()}.` : ""}
          </p>
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
              <PlatformMark platform="instagram" size={32} />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-[17px] font-bold text-[var(--ui-ink)]">
              {profile?.name || (loading ? "Loading…" : "Not available")}
            </p>
            <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
              {profile?.username ? `@${profile.username}` : "—"}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {profile?.status && (
                <span className="rounded-[8px] bg-[var(--ui-sunken)] px-3 py-1 text-[12px] font-semibold text-[var(--ui-ink)]">
                  {profile.status === "connected" ? "Connected" : profile.status}
                </span>
              )}
              {profile?.eligibility && (
                <span className="rounded-[8px] border border-[var(--ui-line)] px-3 py-1 text-[12px] text-[var(--ui-ink-2)]">
                  {profile.eligibility}
                </span>
              )}
              {profile?.parent_page_name && (
                <span className="rounded-[8px] border border-[var(--ui-line)] px-3 py-1 text-[12px] text-[var(--ui-ink-2)]">
                  via {profile.parent_page_name}
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className={PANEL}>
        <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Profile details</h3>
        <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
          Instagram does not let apps change these — edit them in the Instagram app, and Sayvors will
          pick the change up on the next refresh.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Row label="Username" value={profile?.username ? `@${profile.username}` : "—"} />
          <Row
            label="Website"
            value={profile?.website || "—"}
            {...(profile?.website ? { href: profile.website } : {})}
          />
          <div className="sm:col-span-2">
            <Row label="Bio" value={profile?.biography || "—"} />
          </div>
          <Row
            label="Open in Instagram"
            value={handle ? "View the live profile" : "—"}
            {...(handle ? { href: handle } : {})}
          />
        </div>
      </section>

      {profile && (
        <section className={PANEL}>
          <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Audience</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Counter label="Followers" value={profile.followers_count} />
            <Counter label="Following" value={profile.follows_count} />
            <Counter label="Posts" value={profile.media_count} />
          </div>
        </section>
      )}

      <section className={PANEL}>
        <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">Posts</h3>
        <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
          Your feed, laid out like your profile. Live stories sit on top; tap any
          post to open it with its comments.
        </p>
        <div className="mt-4 space-y-5">
          <StoriesStrip igId={asset.external_asset_id} />
          <PostsGrid
            igId={asset.external_asset_id}
            accountUsername={profile?.username ?? asset.username}
          />
        </div>
      </section>
    </div>
  );
}

/*
 * The posts tab: the composer on top, the feed below. Publishing bumps a
 * version counter that remounts the grid — its fetch is mount-owned, so a
 * fresh post shows up without the tenant hunting for a refresh button.
 */
function PostsTab({ igId, accountUsername }: { igId: string; accountUsername?: string | null }) {
  const [version, setVersion] = useState(0);
  return (
    <section className={PANEL}>
      <h3 className={`text-[15px] font-semibold ${INK}`}>Posts</h3>
      <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
        Laid out like your profile. Tap a post to open it with its
        comments, likes and reach.
      </p>
      <div className="mt-4 space-y-5">
        <PostComposer
          igId={igId}
          accountUsername={accountUsername}
          onPublished={() => setVersion((v) => v + 1)}
        />
        <PostsGrid
          key={version}
          igId={igId}
          accountUsername={accountUsername}
        />
      </div>
    </section>
  );
}

export default function InstagramHub() {
  const [tab, setTab] = useState<Tab>("profile");
  const [assets, setAssets] = useState<MetaAsset[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchMetaAssets("instagram");
        if (!cancelled) {
          const list = (data.assets ?? []).filter((a) => a.active);
          setAssets(list);
          setSelected((i) => Math.min(i, Math.max(0, list.length - 1)));
        }
      } catch {
        if (!cancelled) setError("Could not load your Instagram accounts.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const active = TABS.find((t) => t.key === tab)!;
  const account = assets && assets.length > 0 ? assets[Math.min(selected, assets.length - 1)] : null;

  return (
    <div className="team-ui h-full overflow-y-auto p-4 pb-24 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-[20px] font-bold text-[var(--ui-ink)]">
            <PlatformMark platform="instagram" size={22} />
            Instagram
          </h1>
          <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
            Accounts, messages, posts and comments.
          </p>
        </div>
      </div>

      <nav aria-label="Instagram sections" className="mt-6 flex flex-wrap gap-1 border-b border-[var(--ui-line)]">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            aria-current={tab === t.key ? "page" : undefined}
            className={`rounded-t-[8px] border-b-2 px-4 py-2.5 text-[13px] font-semibold ${
              tab === t.key
                ? "border-[var(--ui-ink)] text-[var(--ui-ink)]"
                : "border-transparent text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
            }`}
          >
            {t.label}
            {!t.live && <span className="ml-1.5 text-[11px] font-normal text-[var(--ui-ink-2)]">soon</span>}
          </button>
        ))}
      </nav>

      <div className="mt-6">
        {error && (
          <p role="alert" className={`rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4 text-[13px] font-bold ${INK}`}>
            {error}
          </p>
        )}

        {!error && assets === null && (
          <p className={`text-[13px] ${INK2}`}>Loading your Instagram accounts…</p>
        )}

        {!error && assets !== null && assets.length === 0 && (
          <div className={PANEL}>
            <h3 className={`text-[15px] font-semibold ${INK}`}>No Instagram account connected</h3>
            <p className={`mt-2 text-[13px] ${INK2}`}>
              Connect Instagram from the channels page, then come back here.
            </p>
          </div>
        )}

        {!error && account && assets !== null && assets.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Instagram accounts">
            {assets.map((a, i) => (
              <button
                key={a.id}
                type="button"
                role="tab"
                aria-selected={i === selected}
                onClick={() => setSelected(i)}
                className={`ui-chip px-3 py-1.5 text-[12px] font-semibold ${
                  i === selected
                    ? `bg-[var(--ui-ink)] text-[var(--ui-on-ink)]`
                    : `bg-[var(--ui-sunken)] ${INK} hover:bg-[var(--ui-line)]`
                }`}
              >
                @{a.username || a.name || a.external_asset_id}
              </button>
            ))}
          </div>
        )}

        {!error && account && (
          active.key === "profile" ? (
            <div className="mt-6">
              <ProfileTab asset={account} />
            </div>
          ) : active.key === "audience" ? (
            <div className="mt-6">
              <AudienceTab igId={account.external_asset_id} />
            </div>
          ) : active.key === "posts" ? (
            <PostsTab igId={account.external_asset_id} accountUsername={account.username} />
          ) : active.key === "comments" ? (
            <div className="mt-6">
              <CommentsTab
                igId={account.external_asset_id}
                accountUsername={account.username}
              />
            </div>
          ) : (
            <div className="mt-6">
              <MessagesTab />
            </div>
          )
        )}
      </div>
    </div>
  );
}