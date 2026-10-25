"use client";

import { useState } from "react";
import PublishedPosts from "@/components/dashboard/PublishedPosts";
import PublishComposer from "@/components/dashboard/publish/PublishComposer";

type View = "feed" | "compose";

export default function PostsMediaPage() {
  const [view, setView] = useState<View>("feed");
  const [scheduleDate, setScheduleDate] = useState<string | null>(null);

  if (view === "compose") {
    return (
      <div className="team-ui flex h-full flex-col">
        <PublishComposer
          initialScheduleDate={scheduleDate}
          onPublished={() => { setScheduleDate(null); setView("feed"); }}
          onCancel={() => { setScheduleDate(null); setView("feed"); }}
        />
      </div>
    );
  }

  return (
    <div className="h-full">
      <PublishedPosts onPublish={(date) => { setScheduleDate(date ?? null); setView("compose"); }} />
    </div>
  );
}
