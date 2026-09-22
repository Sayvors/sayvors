import { redirect } from "next/navigation";

// Automations merged into Channels: every connected location carries its
// AI settings inline. Old bookmarks land on the right page.
export default function AutomationsPage() {
  redirect("/dashboard/channels");
}
