"use client";

import { useState } from "react";
import PublishedPosts from "@/components/dashboard/PublishedPosts";
import PublishComposer from "@/components/dashboard/publish/PublishComposer";

/*
 * Posts & Media — one page, no tabs.
 *
 * The feed lists every post published through the composer, on every
 * connected network (Instagram, Facebook, WhatsApp, Google Business
 * Profile). "Publish" opens the unified composer, which pushes the same
 * post to every selected destination; the post lands back in the feed
 * with its status.
 *
 * `/dashboard/channels/publish` redirects here.
 */

type View = "feed" | "compose";

export default function PostsMediaPage() {
  const [view, setView] = useState<View>("feed");

  if (view === "compose") {
    return (
      <div className="h-full">
        <PublishComposer onPublished={() => setView("feed")} onCancel={() => setView("feed")} />
      </div>
    );
  }

  return (
    <div className="h-full">
      <PublishedPosts onPublish={() => setView("compose")} />
    </div>
  );
}
