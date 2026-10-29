import { redirect } from "next/navigation";

/** Catalog is a tab of the WhatsApp hub now. */
export default function CatalogRedirectPage() {
  redirect("/dashboard/channels/whatsapp?tab=catalog");
}
