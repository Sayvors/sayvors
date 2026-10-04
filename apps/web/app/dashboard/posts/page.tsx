import { redirect } from "next/navigation";

// Posts and Media merged into one page — old links land on the merged tabs.
export default function PostsRedirect() {
  redirect("/dashboard/posts-media");
}