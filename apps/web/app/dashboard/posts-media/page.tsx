"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import PostsPage from "@/components/dashboard/PostsPage";
import MediaPage from "@/components/dashboard/MediaPage";
import { useI18n } from "@/lib/i18n/I18nProvider";

// Posts and Media were two sidebar entries; they merged into this one page.
// The two halves keep their own toolbars and state — the switcher only picks
// which one fills the page. Old /dashboard/media links land with the media
// half raised (?tab=media).
export default function PostsMediaPage() {
  return (
    <Suspense>
      <PostsMediaInner />
    </Suspense>
  );
}

function PostsMediaInner() {
  const { t } = useI18n();
  const params = useSearchParams();
  const [tab, setTab] = useState<"posts" | "media">(
    params.get("tab") === "media" ? "media" : "posts"
  );

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-2 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex gap-1 rounded-xl bg-ink/[0.04] p-1 dark:bg-fog/[0.06]" role="tablist" aria-label={t.nav.postsMedia}>
          {([
            { key: "posts", label: t.nav.posts },
            { key: "media", label: t.nav.media },
          ] as const).map((seg) => (
            <button
              key={seg.key}
              role="tab"
              aria-selected={tab === seg.key}
              onClick={() => setTab(seg.key)}
              className={`rounded-lg px-4 py-1.5 text-[12px] font-semibold transition ${
                tab === seg.key
                  ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-fog"
                  : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
              }`}
            >
              {seg.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        {tab === "posts" ? <PostsPage /> : <MediaPage />}
      </div>
    </div>
  );
}