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
import LeadsTab from "./LeadsTab";
import { useI18n } from "@/lib/i18n/I18nProvider";

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

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

type Tab = "profile" | "audience" | "leads" | "posts" | "comments";

const TAB_ORDER: { key: Tab; live: boolean }[] = [
  { key: "profile", live: true },
  { key: "audience", live: true },
  { key: "leads", live: true },
  { key: "posts", live: true },
  { key: "comments", live: true },
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

function Counter({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-4 py-3">
      <p className="text-[20px] font-bold tabular-nums text-[var(--ui-ink)]">
        {value}
      </p>
      <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">{label}</p>
    </div>
  );
}

function ProfileTab({ asset }: { asset: MetaAsset }) {
  const { t, locale } = useI18n();
  const g = t.channelHub.instagram;
  const fmtNum = (n: number) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const when = (value: string) =>
    new Date(value).toLocaleString(locale === "ar" ? "ar-SA" : "en-US");
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
          setError(e instanceof Error ? e.message : g.profileError);
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
          <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">{g.account}</h3>
          <div className="flex items-center gap-2">
            {profile?.stale && (
              <span className="rounded-[8px] bg-[var(--ui-ink)] px-3 py-1 text-[12px] font-bold text-[var(--ui-on-ink)]">
                {g.cached}
              </span>
            )}
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="ui-btn rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
            >
              {loading ? g.refreshing : g.refresh}
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
              {g.retry}
            </button>
          </div>
        )}

        {profile?.stale && !error && (
          <p className="mt-4 rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] text-[var(--ui-ink-2)]">
            {g.staleNote}
            {profile.synced_at ? ` ${fill(g.savedAt, { when: when(profile.synced_at) })}` : ""}
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
              {profile?.name || (loading ? g.profileLoading : g.notAvailable)}
            </p>
            <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
              {profile?.username ? `@${profile.username}` : "—"}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {profile?.status && (
                <span className="rounded-[8px] bg-[var(--ui-sunken)] px-3 py-1 text-[12px] font-semibold text-[var(--ui-ink)]">
                  {profile.status === "connected" ? g.connected : profile.status}
                </span>
              )}
              {profile?.eligibility && (
                <span className="rounded-[8px] border border-[var(--ui-line)] px-3 py-1 text-[12px] text-[var(--ui-ink-2)]">
                  {profile.eligibility}
                </span>
              )}
              {profile?.parent_page_name && (
                <span className="rounded-[8px] border border-[var(--ui-line)] px-3 py-1 text-[12px] text-[var(--ui-ink-2)]">
                  {fill(g.via, { name: profile.parent_page_name })}
                </span>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className={PANEL}>
        <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">{g.details}</h3>
        <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
          {g.detailsBody}
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Row label={g.username} value={profile?.username ? `@${profile.username}` : "—"} />
          <Row
            label={g.website}
            value={profile?.website || "—"}
            {...(profile?.website ? { href: profile.website } : {})}
          />
          <div className="sm:col-span-2">
            <Row label={g.bio} value={profile?.biography || "—"} />
          </div>
          <Row
            label={g.openIn}
            value={handle ? g.viewProfile : "—"}
            {...(handle ? { href: handle } : {})}
          />
        </div>
      </section>

      {profile && (
        <section className={PANEL}>
          <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">{g.audience}</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Counter label={g.followers} value={fmtNum(profile.followers_count)} />
            <Counter label={g.following} value={fmtNum(profile.follows_count)} />
            <Counter label={g.posts} value={fmtNum(profile.media_count)} />
          </div>
        </section>
      )}

      <section className={PANEL}>
        <h3 className="text-[15px] font-semibold text-[var(--ui-ink)]">{g.posts}</h3>
        <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
          {g.postsBody}
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
  const { t } = useI18n();
  const g = t.channelHub.instagram;
  const [version, setVersion] = useState(0);
  return (
    <section className={PANEL}>
      <h3 className={`text-[15px] font-semibold ${INK}`}>{g.posts}</h3>
      <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
        {g.postsTabBody}
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
  const { t } = useI18n();
  const h = t.channelHub;
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
        if (!cancelled) setError(h.instagram.loadError);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [h]);
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
            {h.instagram.subtitle}
          </p>
        </div>
      </div>

      <nav aria-label={h.instagram.sectionsAria} className="mt-6 flex flex-wrap gap-1 border-b border-[var(--ui-line)]">
        {TAB_ORDER.map((tabDef) => (
          <button
            key={tabDef.key}
            type="button"
            onClick={() => setTab(tabDef.key)}
            aria-current={tab === tabDef.key ? "page" : undefined}
            className={`rounded-t-[8px] border-b-2 px-4 py-2.5 text-[13px] font-semibold ${
              tab === tabDef.key
                ? "border-[var(--ui-ink)] text-[var(--ui-ink)]"
                : "border-transparent text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
            }`}
          >
            {h.tabs[tabDef.key]}
            {!tabDef.live && <span className="ml-1.5 text-[11px] font-normal text-[var(--ui-ink-2)]">{h.soon}</span>}
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
          <p className={`text-[13px] ${INK2}`}>{h.instagram.loading}</p>
        )}

        {!error && assets !== null && assets.length === 0 && (
          <div className={PANEL}>
            <h3 className={`text-[15px] font-semibold ${INK}`}>{h.instagram.emptyTitle}</h3>
            <p className={`mt-2 text-[13px] ${INK2}`}>
              {h.instagram.emptyBody}
            </p>
          </div>
        )}

        {!error && account && assets !== null && assets.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label={h.instagram.accountsAria}>
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
          tab === "profile" ? (
            <div className="mt-6">
              <ProfileTab asset={account} />
            </div>
          ) : tab === "audience" ? (
            <div className="mt-6">
              <AudienceTab igId={account.external_asset_id} />
            </div>
          ) : tab === "posts" ? (
            <PostsTab igId={account.external_asset_id} accountUsername={account.username} />
          ) : tab === "comments" ? (
            <div className="mt-6">
              <CommentsTab
                igId={account.external_asset_id}
                accountUsername={account.username}
              />
            </div>
          ) : (
            <div className="mt-6">
              <LeadsTab />
            </div>
          )
        )}
      </div>
    </div>
  );
}