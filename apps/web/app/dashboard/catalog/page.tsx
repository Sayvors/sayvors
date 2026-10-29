import { redirect } from "next/navigation";

/** The catalog lives in the WhatsApp hub; keep old bookmarks working. */
export default function LegacyCatalogPage() {
  redirect("/dashboard/channels/whatsapp?tab=catalog");
}
