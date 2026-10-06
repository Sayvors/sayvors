import { redirect } from "next/navigation";

// Inbox lives under Channels home now. Old bookmarks land on the right page.
export default function InboxRedirect() {
  redirect("/dashboard/channels/inbox");
}
