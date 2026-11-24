"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import PublishedPosts from "@/components/dashboard/PublishedPosts";
import PublishComposer from "@/components/dashboard/publish/PublishComposer";
import GoogleLiveGallery from "@/components/dashboard/GoogleLiveGallery";
import LogoLoader from "@/components/LogoLoader";

type View = "feed" | "compose";
type Tab = "posts" | "google";

function normalizeTab(v: string | null): Tab {
  if (v === "google") return "google";
  return "posts";
}

function PostsMediaInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [view, setView] = useState<View>("feed");
  const [tab, setTab] = useState<Tab>(() => normalizeTab(searchParams.get("tab")));
  const [scheduleDate, setScheduleDate] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const changeTab = (next: Tab) => {
    setTab(next);
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", next);
    router.replace(`/dashboard/posts-media?${params.toString()}`, { scroll: false });
  };

  if (view === "compose") {
    return (
      <div className="team-ui flex h-full flex-col bg-[var(--ui-page)]">
        <PublishComposer
          initialScheduleDate={scheduleDate}
          onNotice={(text) => setNotice(text)}
          onPublished={() => { setScheduleDate(null); setView("feed"); setTab("posts"); changeTab("posts"); }}
          onCancel={() => { setScheduleDate(null); setView("feed"); }}
        />
      </div>
    );
  }

  return (
    <div className="team-ui flex h-full flex-col bg-[var(--ui-page)]">
      {notice && (
        <div className="shrink-0 px-6 pt-4">
          <div className="mx-auto max-w-[1280px] xl:max-w-[1600px] 2xl:max-w-[1800px]">
            <p role="status" className="flex items-start gap-2.5 rounded-[8px] border border-amber-500/30 bg-amber-50 px-4 py-3 text-[13px] font-medium text-amber-800 shadow-[0_12px_28px_-22px_rgba(61,29,110,0.45)] dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-300">
              <svg className="mt-0.5 h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <circle cx="12" cy="12" r="9" />
                <path d="M12 11v5" strokeLinecap="round" />
                <path d="M12 8h.01" strokeLinecap="round" />
              </svg>
              <span>{notice}</span>
            </p>
          </div>
        </div>
      )}

      {/* Section switch — a compact segmented control, shared by both views. */}
      <div className="shrink-0 border-b border-ink/[0.06] bg-white px-6 py-3 dark:border-fog/[0.06] dark:bg-ink">
        <div className="mx-auto flex max-w-[1280px] justify-center xl:max-w-[1600px] 2xl:max-w-[1800px]">
          <nav aria-label="Posts and media views" className="flex items-center gap-1 rounded-[8px] bg-ink/[0.05] p-1 dark:bg-fog/[0.06]">
            {([
              {
                key: "posts",
                label: "Posts",
                icon: (
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <rect x="4" y="3" width="16" height="18" rx="2" />
                    <path d="M8 8h8M8 12h8M8 16h5" strokeLinecap="round" />
                  </svg>
                ),
              },
              {
                key: "google",
                label: "Live on Google",
                icon: (
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <rect x="3" y="4" width="18" height="16" rx="2" />
                    <circle cx="8.5" cy="9" r="1.5" />
                    <path d="M4 17l5-5 4 4 3-3 4 4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ),
              },
            ] as const).map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => changeTab(t.key)}
                aria-current={tab === t.key ? "page" : undefined}
                className={`flex items-center gap-2 rounded-[8px] px-5 py-2 text-[13px] font-bold transition duration-200 active:translate-y-0.5 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 ${
                  tab === t.key
                    ? "bg-white text-deep-violet shadow-[0_8px_18px_-12px_rgba(61,29,110,0.55)] dark:bg-fog/10 dark:text-fog"
                    : "text-ink/45 hover:bg-ink/[0.03] hover:text-ink dark:text-fog/45"
                }`}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* One scroll container for the whole page — no nested scrollbars.
          The posts tab is full-bleed on purpose: PublishedPosts paints its
          own header band (bg-white) edge-to-edge, matching the tabs band
          above; capping the wrapper made that band read as a floating card
          with page-grey margins on wide screens. The Google tab has no band
          and keeps the centered container. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "posts" ? (
          <div className="pb-6">
            <PublishedPosts onPublish={(date) => { setScheduleDate(date ?? null); setView("compose"); }} />
          </div>
        ) : (
          <div className="mx-auto max-w-[1280px] px-6 pb-24 pt-6 xl:max-w-[1600px] 2xl:max-w-[1800px]">
            <GoogleLiveGallery />
          </div>
        )}
      </div>
    </div>
  );
}

export default function PostsMediaPage() {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>}>
      <PostsMediaInner />
    </Suspense>
  );
}
