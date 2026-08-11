import Sidebar from "@/components/dashboard/Sidebar";
import Header from "@/components/dashboard/Header";
import { ThemeProvider } from "@/components/ThemeProvider";
import { AuthGuard } from "@/components/AuthGuard";
import JobPanel from "@/components/dashboard/JobPanel";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AuthGuard>
        <div className="flex h-screen overflow-hidden bg-fog font-sans text-ink dark:bg-ink dark:text-fog">
          <Sidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            <Header />
            <main className="flex-1 overflow-hidden">
              {children}
            </main>
          </div>
        </div>
        <JobPanel />
      </AuthGuard>
    </ThemeProvider>
  );
}
