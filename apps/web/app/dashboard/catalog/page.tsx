import { redirect } from "next/navigation";

/** The catalog lives in the WhatsApp area; keep old bookmarks working. */
export default function LegacyCatalogPage() {
  redirect("/dashboard/channels/whatsapp/catalog");
}
