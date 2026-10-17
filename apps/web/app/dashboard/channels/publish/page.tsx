"use client";

import PublishComposer from "@/components/dashboard/publish/PublishComposer";

/*
 * Publish a post to every connected social channel — the unified composer
 * sits under Channels because that is where its destinations live. Body
 * renders the full-height team-ui shell so the composer inherits the
 * locked three-colour palette the other channel hubs use.
 */
export default function PublishPostPage() {
  return (
    <div className="team-ui flex h-full flex-col">
      <PublishComposer />
    </div>
  );
}
