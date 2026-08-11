"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import { use } from "react";

export default function ContactDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <Breadcrumbs
          items={[
            { label: "Contacts", href: "/dashboard/contacts" },
            { label: `Contact #${id}` },
          ]}
        />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Contact Details</h1>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-ink/[0.06] bg-white p-5 lg:col-span-1 dark:border-fog/[0.06] dark:bg-ink">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet/10 text-[18px] font-bold text-deep-violet">
            SC
          </div>
          <h2 className="mt-3 text-[16px] font-semibold text-ink dark:text-fog">Sarah Chen</h2>
          <p className="text-[12px] text-ink/40 dark:text-fog/40">sarah@example.com</p>
          <div className="mt-4 space-y-2">
            <div className="flex justify-between text-[12px]">
              <span className="text-ink/40 dark:text-fog/40">Source</span>
              <span className="font-medium text-ink dark:text-fog">Instagram</span>
            </div>
            <div className="flex justify-between text-[12px]">
              <span className="text-ink/40 dark:text-fog/40">Score</span>
              <span className="font-medium text-emerald-600">92</span>
            </div>
            <div className="flex justify-between text-[12px]">
              <span className="text-ink/40 dark:text-fog/40">Value</span>
              <span className="font-semibold text-ink dark:text-fog">$2,400</span>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-ink/[0.06] bg-white p-5 lg:col-span-2 dark:border-fog/[0.06] dark:bg-ink">
          <h3 className="text-[14px] font-semibold text-ink dark:text-fog">Activity</h3>
          <p className="mt-4 text-[12px] text-ink/40 dark:text-fog/40">No recent activity.</p>
        </div>
      </div>
    </div>
  );
}
