import { redirect } from "next/navigation";

export default function RootPage() {
  // TODO: check auth session cookie
  // if authenticated → redirect("/dashboard")
  // if not → redirect("/login")
  redirect("/login");
}
