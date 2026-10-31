import type { Metadata } from "next";
import { ThemeProvider } from "@/components/ThemeProvider";

export const metadata: Metadata = {
  title: "Sayvors Admin",
  robots: { index: false, follow: false },
};

/* Standalone shell: no tenant sidebar, no AuthGuard — platform operators use
 * the separate admin password, not a tenant session. */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <div className="min-h-screen bg-fog font-sans text-ink dark:bg-ink dark:text-fog">
        {children}
      </div>
    </ThemeProvider>
  );
}
