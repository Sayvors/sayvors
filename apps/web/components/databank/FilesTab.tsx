"use client";

interface FilesTabProps {
  documents: {
    id: string;
    filename: string;
    size: number;
    status: "pending" | "processing" | "completed" | "failed";
    progress?: number;
    stage?: string;
    error?: string;
  }[];
  pendingCount: number;
  onUpload: (files: FileList | null) => void;
  onProcessAll: () => void;
  onProcessDoc: (docId: string) => void;
  onDeleteDoc: (docId: string) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  formatBytes: (bytes: number) => string;
}

export default function FilesTab({
  documents,
  pendingCount,
  onUpload,
  onProcessAll,
  onProcessDoc,
  onDeleteDoc,
  onDrop,
  onDragOver,
  formatBytes,
}: FilesTabProps) {
  return (
    <div className="space-y-4">
      {/* Upload Zone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition cursor-pointer border-ink/15 hover:border-deep-violet/30 hover:bg-deep-violet/[0.02]"
      >
        <label className="flex flex-col items-center gap-3 cursor-pointer">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-deep-violet/10 text-deep-violet">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
          </div>
          <div className="text-center">
            <p className="text-[13px] font-semibold text-ink">
              Drag & drop files here
            </p>
            <p className="text-[11px] text-ink/40 mt-1">
              or <span className="font-semibold text-deep-violet">browse</span> to upload
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-1.5 mt-1">
            {["PDF", "DOCX", "TXT", "CSV", "SQL", "XLS"].map((ext) => (
              <span key={ext} className="rounded-md bg-ink/[0.04] px-2 py-0.5 text-[9px] font-semibold text-ink/40">
                {ext}
              </span>
            ))}
          </div>
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.sql"
            onChange={(e) => onUpload(e.target.files)}
            className="hidden"
          />
        </label>
      </div>

      {/* Process All Button */}
      {pendingCount > 0 && (
        <button
          onClick={onProcessAll}
          className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
        >
          Process All ({pendingCount})
        </button>
      )}

      {/* Documents List */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-[13px] font-bold text-ink">Documents</h3>
          <span className="text-[11px] text-ink/40">{documents.length} total</span>
        </div>
        {documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center rounded-xl bg-ink/[0.02]">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ink/[0.04]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-ink/20">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </div>
            <p className="mt-3 text-[13px] font-semibold text-ink/40">No documents yet</p>
            <p className="text-[11px] text-ink/30">Upload files to get started</p>
          </div>
        ) : (
          <div className="space-y-2">
            {documents.map((doc) => (
              <DocumentItem
                key={doc.id}
                doc={doc}
                onProcess={onProcessDoc}
                onDelete={onDeleteDoc}
                formatBytes={formatBytes}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DocumentItem({
  doc,
  onProcess,
  onDelete,
  formatBytes,
}: {
  doc: {
    id: string;
    filename: string;
    size: number;
    status: "pending" | "processing" | "completed" | "failed";
    progress?: number;
    stage?: string;
    error?: string;
  };
  onProcess: (docId: string) => void;
  onDelete: (docId: string) => void;
  formatBytes: (bytes: number) => string;
}) {
  const statusColors: Record<string, string> = {
    completed: "bg-emerald-100 text-emerald-600",
    processing: "bg-deep-violet/10 text-deep-violet",
    failed: "bg-coral/10 text-coral",
    pending: "bg-ink/[0.04] text-ink/40",
  };

  const badgeColors: Record<string, string> = {
    completed: "bg-emerald-100 text-emerald-700",
    processing: "bg-deep-violet/10 text-deep-violet",
    failed: "bg-coral/10 text-coral",
    pending: "bg-ink/[0.06] text-ink/50",
  };

  return (
    <div className="flex items-center gap-3 rounded-xl border-2 border-white bg-white/60 p-3 transition hover:bg-white">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${statusColors[doc.status]}`}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-[12px] font-semibold text-ink truncate">{doc.filename}</p>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold ${badgeColors[doc.status]}`}>
            {doc.status}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] text-ink/35">{formatBytes(doc.size)}</span>
          {doc.stage && <span className="text-[10px] text-deep-violet">{doc.stage}</span>}
        </div>
        {(doc.status === "processing" || (doc.progress !== undefined && doc.progress > 0)) && (
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-ink/[0.06]">
            <div
              className="h-full rounded-full bg-deep-violet transition-all duration-500"
              style={{ width: `${doc.progress ?? 0}%` }}
            />
          </div>
        )}
        {doc.error && <p className="mt-1 text-[10px] text-coral">{doc.error}</p>}
      </div>
      <div className="flex shrink-0 gap-1.5">
        {(doc.status === "pending" || doc.status === "failed") && (
          <button
            onClick={() => onProcess(doc.id)}
            className="rounded-lg bg-deep-violet/10 px-2.5 py-1 text-[10px] font-bold text-deep-violet transition hover:bg-deep-violet/20"
          >
            Process
          </button>
        )}
        <button
          onClick={() => onDelete(doc.id)}
          className="rounded-lg px-2.5 py-1 text-[10px] font-semibold text-ink/30 transition hover:text-coral"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
