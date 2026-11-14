"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteBackup,
  downloadBackup,
  fetchBackups,
  saveBackupConfig,
  triggerBackup,
  type BackupConfig,
  type BackupList,
  type BackupObject,
} from "@/lib/admin-api";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

const STATUS_CLS: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-700",
  running: "bg-blue-100 text-blue-700",
  failed: "bg-red-100 text-red-700",
  deleted: "bg-ink/[0.06] text-ink/50",
};

function fmtBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function BackupRow({ obj, onDelete, onDownload }: {
  obj: BackupObject;
  onDelete: (o: BackupObject) => void;
  onDownload: (o: BackupObject) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const status = obj.status ?? "unknown";
  const statusCls = STATUS_CLS[status] ?? "bg-ink/[0.06] text-ink/50";
  const fname = obj.key.split("/").pop() ?? obj.key;

  return (
    <li className="rounded-[2px] border border-[var(--ui-line)]">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className={`shrink-0 rounded-[2px] px-1.5 py-1 text-[11px] font-semibold text-ink/45 transition hover:text-deep-violet ${FOCUS_RING}`}
          title={expanded ? "Collapse versions" : "Show versions"}
        >
          {expanded ? "▾" : "▸"}
        </button>
        <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink/85" title={obj.key}>
          {fname}
        </span>
        <span className="text-[10.5px] text-ink/40">
          {obj.versions.length > 0 ? `${obj.versions.length} version${obj.versions.length > 1 ? "s" : ""}` : "—"}
        </span>
        <span className="rounded-[2px] bg-ink/[0.05] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink/55">
          {fmtBytes(obj.latest_size_bytes)}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide ${statusCls}`}>
          {status}
        </span>
        {obj.trigger && (
          <span className="rounded-[2px] bg-deep-violet/10 px-1.5 py-0.5 text-[9.5px] font-bold uppercase text-deep-violet">
            {obj.trigger}
          </span>
        )}
        <span className="text-[10.5px] text-ink/40">{fmtTime(obj.run_started_at)}</span>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => void onDownload(obj)}
            disabled={obj.versions.length === 0}
            className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1 text-[10.5px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-40 ${FOCUS_RING}`}
          >
            Download
          </button>
          <button
            type="button"
            onClick={() => onDelete(obj)}
            className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1 text-[10.5px] font-semibold text-ink/60 transition hover:border-coral hover:text-coral ${FOCUS_RING}`}
          >
            Delete
          </button>
        </div>
      </div>
      {expanded && (
        <div className="border-t border-[var(--ui-line)] bg-[var(--ui-sunken)]/40 px-4 py-3">
          {obj.error && (
            <p className="mb-2 font-mono text-[10.5px] text-coral">{obj.error}</p>
          )}
          {obj.versions.length === 0 ? (
            <p className="text-[11px] text-ink/45">No S3 objects found for this backup (may be deleted).</p>
          ) : (
            <ul className="space-y-1">
              {obj.versions.map((v) => (
                <li key={v.version_id} className="flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-ink/60">
                  <span className={`rounded-full px-1.5 py-px text-[9px] font-bold uppercase ${
                    v.is_latest ? "bg-deep-violet/10 text-deep-violet" : "bg-ink/[0.05] text-ink/45"
                  }`}>
                    {v.is_latest ? "latest" : "old"}
                  </span>
                  <span className="truncate">v:{v.version_id}</span>
                  <span>{fmtBytes(v.size_bytes)}</span>
                  <span className="ml-auto text-ink/40">{fmtTime(v.last_modified)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

export default function BackupsPage() {
  const [config, setConfig] = useState<BackupConfig | null>(null);
  const [objects, setObjects] = useState<BackupObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [enabled, setEnabled] = useState(false);
  const [intervalHours, setIntervalHours] = useState(24);
  const [bucket, setBucket] = useState("");
  const [region, setRegion] = useState("eu-north-1");

  const flash = (text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice((n) => (n === text ? null : n)), 5000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: BackupList = await fetchBackups();
      setConfig(data.config);
      setObjects(data.objects);
      setEnabled(data.config.enabled);
      setIntervalHours(data.config.interval_hours);
      setBucket(data.config.bucket);
      setRegion(data.config.region);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load backups.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const saveConfig = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await saveBackupConfig({
        enabled,
        interval_hours: Math.max(1, Math.floor(Number(intervalHours) || 24)),
        bucket: bucket.trim() || undefined,
        region: region.trim() || undefined,
      });
      setConfig(updated);
      setEnabled(updated.enabled);
      setIntervalHours(updated.interval_hours);
      setBucket(updated.bucket);
      setRegion(updated.region);
      flash(updated.enabled ? `Schedule saved — automatic backups every ${updated.interval_hours}h.` : "Schedule disabled.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save schedule.");
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true);
    setError(null);
    try {
      await triggerBackup();
      flash("Backup started in the background — it will appear below when done.");
      window.setTimeout(() => void load(), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start backup.");
    } finally {
      setRunning(false);
    }
  };

  const handleDelete = async (obj: BackupObject) => {
    if (!window.confirm(`Delete backup ${obj.key.split("/").pop()}? This removes it from S3.`)) return;
    setError(null);
    try {
      const res = await deleteBackup(obj.key);
      flash(`Deleted ${res.deleted_versions} version(s).`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    }
  };

  const handleDownload = async (obj: BackupObject) => {
    setError(null);
    try {
      const latest = obj.versions.find((v) => v.is_latest) ?? obj.versions[0];
      const url = await downloadBackup(obj.key, latest?.version_id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Database backups</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            PostgreSQL dumps to S3. Configure automatic schedule, run on demand, and manage stored backups/versions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void runNow()}
            disabled={running || loading}
            className={`btn-primary !px-3 !py-1.5 disabled:opacity-50 ${FOCUS_RING}`}
          >
            {running ? "Starting…" : "Backup now"}
          </button>
          <button
            onClick={() => void load()}
            disabled={loading}
            className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-50 ${FOCUS_RING}`}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {notice && (
        <div role="status" className="panel px-4 py-2.5 text-[12px] font-medium text-ink/70">
          {notice}
        </div>
      )}
      {error && (
        <p role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">
          {error}
        </p>
      )}

      <section className="panel p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-bold text-ink">Automatic schedule</h2>
            <p className="mt-0.5 text-[11.5px] text-ink/50">
              The worker runs a backup when the next run time passes. Disable to stop automatic backups.
            </p>
          </div>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 accent-deep-violet"
            />
            <span className="text-[12px] font-semibold text-ink/70">Enabled</span>
          </label>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-ink/50">Interval (hours)</label>
            <input
              type="number"
              min={1}
              max={720}
              value={intervalHours}
              onChange={(e) => setIntervalHours(Number(e.target.value))}
              className="input-field"
            />
            <p className="mt-0.5 text-[10px] text-ink/40">1h–720h (30 days)</p>
          </div>
          <div className="sm:col-span-2 lg:col-span-1">
            <label className="mb-1 block text-[11px] font-semibold text-ink/50">S3 bucket</label>
            <input
              value={bucket}
              onChange={(e) => setBucket(e.target.value)}
              placeholder="sayvors-prod-backups-…"
              className="input-field font-mono text-[11px]"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold text-ink/50">Region</label>
            <input
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="input-field font-mono text-[11px]"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-ink/[0.05] pt-3">
          <button
            onClick={() => void saveConfig()}
            disabled={saving || loading}
            className={`btn-primary !px-3 !py-1.5 disabled:opacity-50 ${FOCUS_RING}`}
          >
            {saving ? "Saving…" : "Save schedule"}
          </button>
          {config && (
            <div className="flex flex-wrap gap-4 text-[11px] text-ink/55">
              <span><strong className="text-ink/80">Last run:</strong> {fmtTime(config.last_run_at)}</span>
              <span><strong className="text-ink/80">Next run:</strong> {fmtTime(config.next_run_at)}</span>
            </div>
          )}
        </div>
      </section>

      <section className="panel p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-bold text-ink">Backup files</h2>
            <p className="mt-0.5 text-[11.5px] text-ink/50">
              Every attempt is recorded here; S3 object versions are listed per backup.
            </p>
          </div>
          <span className="rounded-full bg-ink/[0.05] px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-wide text-ink/55">
            {objects.length} backup{objects.length === 1 ? "" : "s"}
          </span>
        </div>

        {loading ? (
          <div className="mt-3 space-y-2" aria-hidden>
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-[2px] bg-ink/[0.05]" />
            ))}
          </div>
        ) : objects.length === 0 ? (
          <div className="mt-3 rounded-[2px] border border-dashed border-[var(--ui-line-strong)] p-6 text-center text-[12px] text-ink/40">
            No backups yet. Run one with “Backup now”.
          </div>
        ) : (
          <ul className="mt-3 space-y-2">
            {objects.map((obj) => (
              <BackupRow key={obj.key + (obj.run_id ?? "")} obj={obj} onDelete={handleDelete} onDownload={handleDownload} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
