import Sidebar from "@/components/dashboard/Sidebar";
import Header from "@/components/dashboard/Header";
import SayvorsChat from "@/components/chat/SayvorsChat";
import TourProvider from "@/components/tour/TourProvider";
import ToastProvider from "@/components/feedback/ToastStack";
import MessageToasts from "@/components/feedback/MessageToasts";
import UpgradePrompt from "@/components/billing/UpgradePrompt";
import UsageBanner from "@/components/billing/UsageBanner";
import ConnectImportLauncher from "@/components/channels/ConnectImportLauncher";
import { ThemeProvider } from "@/components/ThemeProvider";
import { AuthGuard } from "@/components/AuthGuard";
import { I18nProvider } from "@/lib/i18n/I18nProvider";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AuthGuard>
        <I18nProvider>
          <ToastProvider>
          <TourProvider>
            {/* Fixed to the viewport, not just 100vh in flow: an in-flow shell
                can still grow the document if any descendant escapes clipping
                (a popup, a tooltip, a tall panel), which gives the dashboard a
                second scrollbar and a blank strip under the sidebar. A fixed
                shell cannot contribute to document height at all. */}
            <div className="fixed inset-0 flex overflow-hidden bg-fog font-sans text-ink dark:bg-ink dark:text-fog">
              <Sidebar />
              <div className="flex flex-1 flex-col overflow-hidden">
                <Header />
                <UsageBanner />
                <main className="flex-1 overflow-hidden">
                  {children}
                </main>
              </div>
              <SayvorsChat />
              <MessageToasts />
              <UpgradePrompt />
              <ConnectImportLauncher />
            </div>
          </TourProvider>
          </ToastProvider>
        </I18nProvider>
      </AuthGuard>
    </ThemeProvider>
  );
}
