"use client";

import { useEffect, useState } from "react";
import {
  fetchMetaAssets,
  type MetaAsset,
} from "@/lib/api-meta";
import PlatformMark from "@/components/channels/PlatformMark";
import CommentsTab from "./CommentsTab";
import MessagesTab from "./MessagesTab";
import PostsTab from "./PostsTab";
import ProfileTab from "./ProfileTab";
import { INK, INK2 } from "../instagram/ui";

/*
 * Facebook Page hub.
 *
 * Same shell as the Instagram hub: the tenant's own connected Pages as
 * chips, four tabs under them. Everything here acts on the tenant's OWN
 * Page — their posts, the comments people leave on those posts, the
 * messages people send it. Nothing auto-posts; publishing is a button.
 */

const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

type Tab = "profile" | "messages" | "posts" | "comments";

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "messages", label: "Messages" },
  { key: "posts", label: "Posts" },
  { key: "comments", label: "Comments" },
];

export default function FacebookHub() {
  const [tab, setTab] = useState<Tab>("profile");
  const [assets, setAssets] = useState<MetaAsset[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchMetaAssets("facebook");
        if (!cancelled) {
          const list = (data.assets ?? []).filter(
            (a) => a.active && a.asset_type === "page"
          );
          setAssets(list);
          setSelected((i) => Math.min(i, Math.max(0, list.length - 1)));
        }
      } catch {
        if (!cancelled) setError("Could not load your Facebook Pages.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const active = TABS.find((t) => t.key === tab)!;
  const page = assets && assets.length > 0 ? assets[Math.min(selected, assets.length - 1)] : null;

  return (
    <div className="team-ui h-full overflow-y-auto p-4 pb-24 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-[20px] font-bold text-[var(--ui-ink)]">
            <PlatformMark platform="facebook" size={22} />
            Facebook
          </h1>
          <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
            Pages, messages, posts and comments.
          </p>
        </div>
      </div>

      <nav aria-label="Facebook sections" className="mt-6 flex flex-wrap gap-1 border-b border-[var(--ui-line)]">
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
          <p className={`text-[13px] ${INK2}`}>Loading your Facebook Pages…</p>
        )}

        {!error && assets !== null && assets.length === 0 && (
          <div className={PANEL}>
            <h3 className={`text-[15px] font-semibold ${INK}`}>No Facebook Page connected</h3>
            <p className={`mt-2 text-[13px] ${INK2}`}>
              Connect Facebook from the channels page, then come back here.
            </p>
          </div>
        )}

        {!error && page && assets !== null && assets.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Facebook Pages">
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
                {a.name || a.external_asset_id}
              </button>
            ))}
          </div>
        )}

        {!error && page && (
          active.key === "profile" ? (
            <div className="mt-6">
              <ProfileTab asset={page} />
            </div>
          ) : active.key === "messages" ? (
            <div className="mt-6">
              <MessagesTab />
            </div>
          ) : active.key === "posts" ? (
            <div className="mt-6">
              <PostsTab pageId={page.external_asset_id} />
            </div>
          ) : (
            <div className="mt-6">
              <CommentsTab
                pageId={page.external_asset_id}
                pageName={page.name}
              />
            </div>
          )
        )}
      </div>
    </div>
  );
}
