import { redirect } from "next/navigation";

/*
 * The composer moved to /dashboard/posts-media (one hub owns publishing
 * across social + Google and the published-post list). Old links keep
 * working through this redirect.
 */
export default function PublishRedirectPage() {
  redirect("/dashboard/posts-media");
}
