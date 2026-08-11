"use client";

type DatabankTab = "files" | "crawler";

interface DatabankTabsProps {
  activeTab: DatabankTab;
  onTabChange: (tab: DatabankTab) => void;
}

const tabs: { id: DatabankTab; label: string; icon: React.ReactNode }[] = [
  {
    id: "files",
    label: "Files",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
    ),
  },
  {
    id: "crawler",
    label: "Website Crawler",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
        <circle cx="12" cy="12" r="10" />
        <path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
      </svg>
    ),
  },
];

export default function DatabankTabs({ activeTab, onTabChange }: DatabankTabsProps) {
  return (
    <div className="flex gap-0 border-b border-deep-violet/10 px-5">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={`relative flex items-center gap-1.5 px-4 py-3 text-[12px] font-semibold transition whitespace-nowrap ${
            activeTab === tab.id
              ? "text-deep-violet"
              : "text-ink/45 hover:text-ink/65"
          }`}
        >
          {tab.icon}
          {tab.label}
          {activeTab === tab.id && (
            <span className="absolute bottom-0 left-0 right-0 h-[2.5px] rounded-t-full bg-deep-violet" />
          )}
        </button>
      ))}
    </div>
  );
}
