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
import { useI18n } from "@/lib/i18n/I18nProvider";

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

const TAB_ORDER: Tab[] = ["profile", "messages", "posts", "comments"];

export default function FacebookHub() {
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
        const data = await fetchMetaAssets("facebook");
        if (!cancelled) {
          const list = (data.assets ?? []).filter(
            (a) => a.active && a.asset_type === "page"
          );
          setAssets(list);
          setSelected((i) => Math.min(i, Math.max(0, list.length - 1)));
        }
      } catch {
        if (!cancelled) setError(h.facebook.loadError);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [h]);
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
            {h.facebook.subtitle}
          </p>
        </div>
      </div>

      <nav aria-label={h.facebook.sectionsAria} className="mt-6 flex flex-wrap gap-1 border-b border-[var(--ui-line)]">
        {TAB_ORDER.map((tabKey) => (
          <button
            key={tabKey}
            type="button"
            onClick={() => setTab(tabKey)}
            aria-current={tab === tabKey ? "page" : undefined}
            className={`rounded-t-[8px] border-b-2 px-4 py-2.5 text-[13px] font-semibold ${
              tab === tabKey
                ? "border-[var(--ui-ink)] text-[var(--ui-ink)]"
                : "border-transparent text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
            }`}
          >
            {h.tabs[tabKey]}
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
          <p className={`text-[13px] ${INK2}`}>{h.facebook.loading}</p>
        )}

        {!error && assets !== null && assets.length === 0 && (
          <div className={PANEL}>
            <h3 className={`text-[15px] font-semibold ${INK}`}>{h.facebook.emptyTitle}</h3>
            <p className={`mt-2 text-[13px] ${INK2}`}>
              {h.facebook.emptyBody}
            </p>
          </div>
        )}

        {!error && page && assets !== null && assets.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label={h.facebook.pagesAria}>
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
          tab === "profile" ? (
            <div className="mt-6">
              <ProfileTab asset={page} />
            </div>
          ) : tab === "messages" ? (
            <div className="mt-6">
              <MessagesTab />
            </div>
          ) : tab === "posts" ? (
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
