"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

export default function SettingsPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <Breadcrumbs items={[{ label: "Settings" }]} />
      <div>
        <h1 className="text-[20px] font-bold text-ink dark:text-fog">Settings</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          Manage your account and preferences.
        </p>
      </div>
    </div>
  );
}
