"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

const COLUMNS = [
  { key: "listing_id", label: "Listing ID", readonly: true, width: "160px" },
  { key: "name", label: "Business name", readonly: false, width: "160px" },
  { key: "phone", label: "Phone", readonly: false, width: "140px" },
  { key: "website", label: "Website", readonly: false, width: "160px" },
  { key: "description", label: "Description", readonly: false, width: "200px" },
  { key: "address", label: "Address", readonly: false, width: "180px" },
  { key: "city", label: "City", readonly: false, width: "100px" },
  { key: "zip_code", label: "Zip", readonly: false, width: "80px" },
  { key: "category", label: "Category", readonly: false, width: "120px" },
  { key: "hours_regular", label: "Hours (JSON)", readonly: false, width: "220px" },
  { key: "special_hours", label: "Special hours (JSON)", readonly: false, width: "180px" },
  { key: "opening_date", label: "Opening date", readonly: false, width: "110px" },
  { key: "attributes", label: "Attributes (JSON)", readonly: false, width: "180px" },
  { key: "service_area", label: "Service area", readonly: false, width: "140px" },
];

type Row = Record<string, string>;

function toStr(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") {
    try { return JSON.stringify(v); } catch { return String(v); }
  }
  return String(v);
}

function dataToRows(data: unknown): Row[] {
  if (!Array.isArray(data)) return [];
  return data.map((r: any) => ({
    listing_id: toStr(r?.listing_id),
    name: toStr(r?.name),
    phone: toStr(r?.phone),
    website: toStr(r?.website),
    description: toStr(r?.description),
    address: toStr(r?.address),
    city: toStr(r?.city),
    zip_code: toStr(r?.zip_code),
    category: toStr(r?.category),
    hours_regular: r?.hours_regular && typeof r.hours_regular === "object" && Object.keys(r.hours_regular).length ? JSON.stringify(r.hours_regular) : toStr(r?.hours_regular),
    special_hours: r?.special_hours && Array.isArray(r.special_hours) && r.special_hours.length ? JSON.stringify(r.special_hours) : toStr(r?.special_hours),
    opening_date: toStr(r?.opening_date),
    attributes: r?.attributes && typeof r.attributes === "object" && Object.keys(r.attributes).length ? JSON.stringify(r.attributes) : toStr(r?.attributes),
    service_area: Array.isArray(r?.service_area) ? r.service_area.join(", ") : toStr(r?.service_area),
  }));
}

function rowsToCsv(rows: Row[]): string {
  const header = COLUMNS.map((c) => c.key).join(",");
  const lines = [header];
  for (const row of rows) {
    const vals = COLUMNS.map((c) => {
      const v = row[c.key] ?? "";
      if (v.includes(",") || v.includes('"') || v.includes("\n")) {
        return `"${v.replace(/"/g, '""')}"`;
      }
      return v;
    });
    lines.push(vals.join(","));
  }
  return lines.join("\n");
}

function parseCsvLine(line: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ",") {
        result.push(current);
        current = "";
      } else {
        current += ch;
      }
    }
  }
  result.push(current);
  return result;
}

function parseCsv(text: string): Row[] {
  const lines = text.split(/\r?\n/);
  if (lines.length < 2) return [];
  const header = parseCsvLine(lines[0]).map((h) => h.trim());
  const newRows: Row[] = [];
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const vals = parseCsvLine(lines[i]);
    const row: Row = {};
    header.forEach((h, idx) => {
      row[h] = vals[idx] ?? "";
    });
    for (const c of COLUMNS) {
      if (!(c.key in row)) row[c.key] = "";
    }
    newRows.push(row);
  }
  return newRows;
}

type Mode = "choose" | "sheet";

export default function BulkEditSheet({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<Mode>("choose");
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [report, setReport] = useState<{ total: number; success: number; failed: number; results: any[] } | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/api/v1/locations/bulk-data");
      setRows(dataToRows(data));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  const openSheet = () => {
    setMode("sheet");
    loadData();
  };

  const downloadCsv = () => {
    const csv = rowsToCsv(rows);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "locations_bulk_edit.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      const parsed = parseCsv(text);
      if (parsed.length === 0) {
        setError("No data rows found in CSV");
        return;
      }
      setRows(parsed);
      setError(null);
    };
    reader.readAsText(file);
  };

  const updateCell = (rowIdx: number, key: string, value: string) => {
    setRows((prev) => {
      const next = [...prev];
      next[rowIdx] = { ...next[rowIdx], [key]: value };
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const csv = rowsToCsv(rows);
      const form = new FormData();
      const blob = new Blob([csv], { type: "text/csv" });
      form.append("file", blob, "bulk_edit.csv");
      const res = await fetch("/api/v1/locations/bulk-upload", {
        method: "POST",
        credentials: "include",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setReport(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="relative flex w-full max-w-6xl flex-col rounded-[2px] bg-white shadow-xl dark:bg-ink" style={{ maxHeight: "90vh" }}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-ink/[0.08] px-4 py-3 dark:border-fog/[0.08]">
          <h2 className="text-[16px] font-bold text-ink dark:text-fog">Bulk edit locations</h2>
          <button onClick={onClose} className="text-ink/40 hover:text-ink dark:text-fog/40">✕</button>
        </div>

        {error && (
          <p role="alert" className="mx-4 mt-3 rounded-[2px] bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
        )}

        {mode === "choose" && (
          <div className="flex-1 p-6">
            <p className="mb-6 text-[13px] text-ink/70 dark:text-fog/70">
              Choose how you want to edit your listing data.
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <button
                onClick={openSheet}
                className="rounded-[2px] border-2 border-deep-violet/20 bg-deep-violet/5 p-6 text-left transition hover:border-deep-violet/40 hover:bg-deep-violet/10"
              >
                <div className="mb-2 text-[24px]">📊</div>
                <p className="text-[14px] font-bold text-ink dark:text-fog">Open spreadsheet here</p>
                <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">
                  Edit all listings in an Excel-like grid right in your browser. Changes are saved when you click "Save changes".
                </p>
              </button>
              <button
                onClick={async () => {
                  try {
                    const res = await fetch("/api/v1/locations/bulk-template", { credentials: "include" });
                    if (!res.ok) throw new Error("Download failed");
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "locations_bulk_template.csv";
                    a.click();
                    URL.revokeObjectURL(url);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "Download failed");
                  }
                }}
                className="rounded-[2px] border-2 border-ink/[0.08] bg-ink/[0.02] p-6 text-left transition hover:border-ink/[0.16] hover:bg-ink/[0.04] dark:border-fog/[0.08] dark:bg-fog/[0.02] dark:hover:border-fog/[0.16]"
              >
                <div className="mb-2 text-[24px]">📥</div>
                <p className="text-[14px] font-bold text-ink dark:text-fog">Download CSV template</p>
                <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">
                  Download a CSV file, edit it in Excel or Google Sheets, then upload it back.
                </p>
              </button>
            </div>
          </div>
        )}

        {mode === "sheet" && (
          <>
            {/* Toolbar */}
            <div className="flex items-center justify-between gap-2 border-b border-ink/[0.08] px-4 py-2 dark:border-fog/[0.08]">
              <div className="flex items-center gap-2">
                <button onClick={downloadCsv} className="flex items-center gap-1.5 rounded-lg border border-ink/[0.12] bg-white px-3 py-1.5 text-[12px] font-medium text-ink/70 transition hover:bg-ink/[0.04] dark:border-fog/[0.12] dark:bg-ink dark:text-fog/70">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
                    <polyline points="7 10 12 15 17 10" strokeLinecap="round" strokeLinejoin="round" />
                    <line x1="12" y1="15" x2="12" y2="3" strokeLinecap="round" />
                  </svg>
                  Download CSV
                </button>
                <span className="text-[11px] text-ink/40 dark:text-fog/40">{rows.length} rows</span>
                {report && report.failed > 0 && (
                  <span className="text-[11px] font-semibold text-red-700">{report.failed} failed</span>
                )}
                {report && report.success > 0 && (
                  <span className="text-[11px] font-semibold text-emerald-700">✓ {report.success} saved</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <label className="cursor-pointer rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-[12px] font-medium text-amber-700 transition hover:bg-amber-100 dark:border-amber-500/40 dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/30">
                  Upload CSV
                  <input type="file" accept=".csv" className="hidden" onChange={handleFileUpload} />
                </label>
              </div>
            </div>

            {/* Spreadsheet grid */}
            <div className="flex-1 overflow-auto">
              {loading ? (
                <div className="flex h-40 items-center justify-center">
                  <p className="text-[13px] text-ink/50 dark:text-fog/50">Loading listing data…</p>
                </div>
              ) : (
                <table className="w-full border-collapse text-[11px]">
                  <thead className="sticky top-0 z-10 bg-ink/[0.03] dark:bg-fog/[0.03]">
                    <tr>
                      {COLUMNS.map((col) => (
                        <th key={col.key} className="whitespace-nowrap border-b border-r border-ink/[0.08] px-2 py-2 text-left font-semibold text-ink/60 dark:border-fog/[0.08] dark:text-fog/60" style={{ minWidth: col.width }}>
                          {col.label}
                          {col.readonly && <span className="ml-1 text-[9px] text-ink/30 dark:text-fog/30">(ro)</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, rowIdx) => (
                      <tr key={rowIdx} className="border-b border-ink/[0.04] dark:border-fog/[0.04]">
                        {COLUMNS.map((col) => (
                          <td key={col.key} className="border-r border-ink/[0.06] px-1 py-0.5 dark:border-fog/[0.06]">
                            {col.readonly ? (
                              <span className="block px-1 py-1 font-mono text-[10px] text-ink/50 dark:text-fog/50">{row[col.key]}</span>
                            ) : (
                              <input
                                type="text"
                                value={row[col.key]}
                                onChange={(e) => updateCell(rowIdx, col.key, e.target.value)}
                                className="w-full bg-transparent px-1 py-1 text-[11px] text-ink outline-none focus:bg-deep-violet/5 dark:text-fog"
                                style={{ minWidth: col.width }}
                              />
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between border-t border-ink/[0.08] px-4 py-3 dark:border-fog/[0.08]">
              <span className="text-[11px] text-ink/40 dark:text-fog/40">{rows.length} rows</span>
              <div className="flex gap-2">
                {report && report.failed > 0 && (
                  <span className="text-[11px] font-semibold text-red-700">
                    {report.failed} failed
                  </span>
                )}
                {report && report.success > 0 && (
                  <span className="text-[11px] font-semibold text-emerald-700">
                    ✓ {report.success} saved
                  </span>
                )}
                <button onClick={() => setMode("choose")} className="rounded-[2px] border border-ink/[0.08] px-3 py-1.5 text-[12px] font-medium text-ink/70 hover:bg-ink/[0.04] dark:border-fog/[0.08] dark:text-fog/70">
                  Back
                </button>
                <button
                  onClick={() => setShowConfirm(true)}
                  disabled={saving || rows.length === 0}
                  className="btn-primary px-4 py-1.5 text-[12px] font-semibold disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save changes"}
                </button>
              </div>
            </div>

            {/* Results detail */}
            {report && report.failed > 0 && (
              <div className="border-t border-ink/[0.08] px-4 py-3 dark:border-fog/[0.08]">
                <p className="mb-2 text-[11px] font-semibold text-red-700">Failed rows:</p>
                <div className="max-h-32 overflow-y-auto text-[11px]">
                  {report.results.filter((r) => r.status === "error").map((r) => (
                    <p key={r.row} className="text-red-600">
                      Row {r.row} ({r.listing_id}): {r.error}
                    </p>
                  ))}
                </div>
              </div>
            )}

        {showConfirm && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/30">
            <div className="w-full max-w-sm rounded-[2px] bg-white p-5 shadow-xl dark:bg-ink">
              <h3 className="text-[14px] font-bold text-ink dark:text-fog">Confirm bulk update</h3>
              <p className="mt-2 text-[12px] text-ink/60 dark:text-fog/60">
                This will update {rows.length} listing(s). Changes to name, phone, website, description,
                address, category, hours, and attributes will be pushed to Google Business Profile.
                This action cannot be undone per-row.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  onClick={() => setShowConfirm(false)}
                  className="rounded-[2px] border border-ink/[0.08] px-3 py-1.5 text-[12px] font-medium text-ink/70 hover:bg-ink/[0.04] dark:border-fog/[0.08] dark:text-fog/70"
                >
                  Cancel
                </button>
                <button
                  onClick={() => { setShowConfirm(false); save(); }}
                  className="btn-primary px-4 py-1.5 text-[12px] font-semibold"
                >
                  Confirm &amp; save
                </button>
              </div>
            </div>
          </div>
        )}
          </>
        )}
      </div>
    </div>
  );
}