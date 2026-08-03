"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

const categories = [
  { name: "Knowledge Base", docs: 24, size: "12.4 MB", icon: "📚", color: "from-deep-violet to-magenta" },
  { name: "Product Catalog", docs: 156, size: "45.2 MB", icon: "📦", color: "from-magenta to-coral" },
  { name: "FAQs", docs: 89, size: "2.1 MB", icon: "❓", color: "from-coral to-orange-400" },
  { name: "Policies", docs: 12, size: "890 KB", icon: "📋", color: "from-emerald-500 to-teal-400" },
  { name: "Templates", docs: 34, size: "3.7 MB", icon: "📝", color: "from-sky-400 to-blue-500" },
  { name: "Training Data", docs: 1200, size: "234 MB", icon: "🧠", color: "from-amber-400 to-orange-400" },
];

export default function DatabankPage() {
  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Databank" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink">Databank</h1>
        <p className="mt-0.5 text-[13px] text-ink/45">Your AI training data and knowledge sources.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {categories.map((c) => (
          <div key={c.name} className="group rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-deep-violet/20 hover:shadow-sm">
            <div className="flex items-center gap-3">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${c.color} text-[18px] text-white`}>
                {c.icon}
              </div>
              <div>
                <p className="text-[14px] font-semibold text-ink group-hover:text-deep-violet">{c.name}</p>
                <p className="text-[11px] text-ink/40">{c.docs} docs · {c.size}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-ink/[0.06] bg-white p-5">
        <h3 className="text-[14px] font-semibold text-ink">Upload Data</h3>
        <p className="mt-1 text-[12px] text-ink/40">Add documents, FAQs, or training data for your AI agents.</p>
        <div className="mt-4 flex h-32 items-center justify-center rounded-lg border-2 border-dashed border-ink/[0.12] bg-fog/30 transition hover:border-deep-violet/30 hover:bg-deep-violet/[0.02]">
          <div className="text-center">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mx-auto h-8 w-8 text-ink/20">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
            <p className="mt-2 text-[12px] text-ink/40">Drag & drop files here, or <span className="font-medium text-deep-violet">browse</span></p>
            <p className="mt-0.5 text-[10px] text-ink/25">PDF, TXT, CSV, DOCX up to 50MB</p>
          </div>
        </div>
      </div>
    </div>
  );
}
