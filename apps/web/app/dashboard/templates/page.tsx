import { redirect } from "next/navigation";

/** Templates live in the WhatsApp hub; keep old bookmarks working. */
export default function LegacyTemplatesPage() {
  redirect("/dashboard/channels/whatsapp?tab=templates");
}
