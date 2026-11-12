"use client";

import { useState } from "react";
import PublishedPosts from "@/components/dashboard/PublishedPosts";
import PublishComposer from "@/components/dashboard/publish/PublishComposer";
import GoogleLiveGallery from "@/components/dashboard/GoogleLiveGallery";

type View = "feed" | "compose";
type Tab = "posts" | "google";

export default function PostsMediaPage() {
  const [view, setView] = useState<View>("feed");
  const [tab, setTab] = useState<Tab>("posts");
  const [scheduleDate, setScheduleDate] = useState<string | null>(null);
  /** Notices that outlive the composer (it closes on publish). */
  const [notice, setNotice] = useState<string | null>(null);

  if (view === "compose") {
    return (
      <div className="team-ui flex h-full flex-col">
        <PublishComposer
          initialScheduleDate={scheduleDate}
          onNotice={(text) => setNotice(text)}
          onPublished={() => { setScheduleDate(null); setView("feed"); setTab("posts"); }}
          onCancel={() => { setScheduleDate(null); setView("feed"); }}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {notice && (
        <div className="shrink-0 px-6 pt-3">
          <div className="mx-auto max-w-6xl">
            <p
              role="status"
              className="rounded-[2px] border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] font-medium text-amber-700 dark:text-amber-400"
            >
              {notice}
            </p>
          </div>
        </div>
      )}
      <div className="shrink-0 border-b border-ink/[0.06] bg-white px-6 pt-3 dark:border-fog/[0.06] dark:bg-ink">
        <div className="mx-auto flex max-w-6xl gap-1">
          {([
            { key: "posts", label: "Posts" },
            { key: "google", label: "Live on Google" },
          ] as const).map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`rounded-t-[2px] px-4 py-2 text-[13px] font-semibold transition ${
                tab === t.key
                  ? "border-b-2 border-deep-violet text-deep-violet"
                  : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {tab === "posts" ? (
          <PublishedPosts onPublish={(date) => { setScheduleDate(date ?? null); setView("compose"); }} />
        ) : (
          <div className="h-full overflow-y-auto">
            <GoogleLiveGallery />
          </div>
        )}
      </div>
    </div>
  );
}
