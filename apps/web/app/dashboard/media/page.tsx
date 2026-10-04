import { redirect } from "next/navigation";

// Posts and Media merged into one page — old media links land with the
// media half raised.
export default function MediaRedirect() {
  redirect("/dashboard/posts-media?tab=media");
}