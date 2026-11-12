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
      <div className="team-ui flex h-full flex-col">
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
    <div className="flex h-full flex-col">
      {notice && (
        <div className="shrink-0 px-6 pt-3">
          <div className="mx-auto max-w-6xl">
            <p role="status" className="rounded-[20px] border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-[13px] font-medium text-amber-700 dark:text-amber-400">
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
              onClick={() => changeTab(t.key)}
              className={`rounded-t-[20px] px-4 py-2.5 text-[13px] font-semibold transition ${
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
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-6 py-5">
          {tab === "posts" && <PublishedPosts onPublish={(date) => { setScheduleDate(date ?? null); setView("compose"); }} />}
          {tab === "google" && <GoogleLiveGallery />}
        </div>
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
