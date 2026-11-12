import { redirect } from "next/navigation";

// The media library lives inside the Publish composer now (step 1), so the
// old media route lands on Posts & Media directly.
export default function MediaRedirect() {
  redirect("/dashboard/posts-media");
}
