import Sidebar from "@/components/dashboard/Sidebar";
import Header from "@/components/dashboard/Header";
import SayvorsChat from "@/components/chat/SayvorsChat";
import { ThemeProvider } from "@/components/ThemeProvider";
import { AuthGuard } from "@/components/AuthGuard";
import { I18nProvider } from "@/lib/i18n/I18nProvider";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AuthGuard>
        <I18nProvider>
          <div className="flex h-screen overflow-hidden bg-fog font-sans text-ink dark:bg-ink dark:text-fog">
            <Sidebar />
            <div className="flex flex-1 flex-col overflow-hidden">
              <Header />
              <main className="flex-1 overflow-hidden">
                {children}
              </main>
            </div>
            <SayvorsChat />
          </div>
        </I18nProvider>
      </AuthGuard>
    </ThemeProvider>
  );
}
