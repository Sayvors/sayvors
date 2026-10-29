import { redirect } from "next/navigation";

/** Templates is a tab of the WhatsApp hub now. */
export default function TemplatesRedirectPage() {
  redirect("/dashboard/channels/whatsapp?tab=templates");
}
