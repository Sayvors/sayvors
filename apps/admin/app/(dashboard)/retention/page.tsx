"use client";

import { useCallback, useEffect, useState } from "react";
import {
  RETENTION_KINDS,
  backupRetentionNow,
  cleanRetentionNow,
  fetchRetentionPolicy,
  fetchRetentionRuns,
  saveRetentionPolicy,
  type RetentionKind,
  type RetentionPolicy,
  type RetentionRun,
} from "@/lib/admin-api";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

const STATUS: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-700",
  running: "bg-blue-100 text-blue-700",
  failed: "bg-red-100 text-red-700",
};

export default function RetentionPage() {
  const [policy, setPolicy] = useState<RetentionPolicy | null>(null);
  const [runs, setRuns] = useState<RetentionRun[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const reload = useCallback(async () => {
    const [p, r] = await Promise.all([fetchRetentionPolicy(), fetchRetentionRuns()]);
    setPolicy(p);
    setRuns(r);
  }, []);

  useEffect(() => {
    void reload().catch((e) => setMessage({ ok: false, text: String(e) }));
  }, [reload]);

  async function save() {
    if (!policy) return;
    setBusy("save");
    setMessage(null);
    try {
      const saved = await saveRetentionPolicy({
        review_log_days: policy.review_log_days,
        connect_event_days: policy.connect_event_days,
        backup_lead_days: policy.backup_lead_days,
        archive_enabled: policy.archive_enabled,
      });
      setPolicy(saved);
      setMessage({ ok: true, text: "Policy saved." });
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function act(kind: RetentionKind, action: "backup" | "clean") {
    setBusy(`${action}:${kind}`);
    setMessage(null);
    try {
      if (action === "clean" && !window.confirm(
        `Clean ${kind} now? Rows older than the configured window will be deleted. If archive is on and the upload fails, nothing is deleted.`
      )) return;
      const result = action === "backup"
        ? await backupRetentionNow(kind)
        : await cleanRetentionNow(kind);
      setMessage({
        ok: true,
        text: action === "backup"
          ? `Archive started for ${result.kind}.`
          : `Deleted ${"deleted" in result ? result.deleted : 0} row(s) from ${result.kind}.`,
      });
      await reload();
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-xl font-bold text-ink">Retention &amp; archive</h1>
      <p className="mt-1 text-[12px] text-ink/55">
        Old AI-generation notes and import progress are archived to private cold storage before deletion, so the live database stays small and a tool-call trace survives for future training.
      </p>

      {message && (
        <div className={`mt-4 rounded-[2px] px-3 py-2 text-[12px] ${message.ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>
          {message.text}
        </div>
      )}

      {policy ? (
        <section className="mt-6 rounded-[2px] border border-[var(--ui-line)] bg-white p-5">
          <h2 className="text-[13px] font-bold text-ink">Policy</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <label className="text-[11px] font-semibold text-ink/60">
              Review generation logs (days)
              <input
                type="number" min={1} max={3650}
                value={policy.review_log_days}
                onChange={(e) => setPolicy({ ...policy, review_log_days: Number(e.target.value) })}
                className={`mt-1 w-full rounded-[2px] border border-[var(--ui-line)] px-2 py-1.5 text-[12px] ${FOCUS}`}
              />
            </label>
            <label className="text-[11px] font-semibold text-ink/60">
              Connect progress (days)
              <input
                type="number" min={1} max={3650}
                value={policy.connect_event_days}
                onChange={(e) => setPolicy({ ...policy, connect_event_days: Number(e.target.value) })}
                className={`mt-1 w-full rounded-[2px] border border-[var(--ui-line)] px-2 py-1.5 text-[12px] ${FOCUS}`}
              />
            </label>
            <label className="text-[11px] font-semibold text-ink/60">
              Archive lead (days before clean)
              <input
                type="number" min={0} max={365}
                value={policy.backup_lead_days}
                onChange={(e) => setPolicy({ ...policy, backup_lead_days: Number(e.target.value) })}
                className={`mt-1 w-full rounded-[2px] border border-[var(--ui-line)] px-2 py-1.5 text-[12px] ${FOCUS}`}
              />
            </label>
          </div>
          <label className="mt-4 flex items-center gap-2 text-[12px] text-ink/70">
            <input
              type="checkbox"
              checked={policy.archive_enabled}
              onChange={(e) => setPolicy({ ...policy, archive_enabled: e.target.checked })}
              className={FOCUS}
            />
            Archive before deleting (fail closed — if S3 fails, nothing is deleted)
          </label>
          <button
            type="button" onClick={() => void save()} disabled={busy !== null}
            className={`mt-4 rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
          >
            {busy === "save" ? "Saving…" : "Save policy"}
          </button>
        </section>
      ) : null}

      <section className="mt-6 rounded-[2px] border border-[var(--ui-line)] bg-white p-5">
        <h2 className="text-[13px] font-bold text-ink">Run now</h2>
        <div className="mt-3 flex flex-wrap gap-3">
          {RETENTION_KINDS.map((kind) => (
            <div key={kind.value} className="flex items-center gap-2 rounded-[2px] border border-[var(--ui-line)] px-3 py-2">
              <span className="text-[11px] font-semibold text-ink/70">{kind.label}</span>
              <button
                type="button" onClick={() => void act(kind.value, "backup")}
                disabled={busy !== null}
                className={`rounded-[2px] border border-deep-violet px-2 py-1 text-[11px] font-bold text-deep-violet disabled:opacity-50 ${FOCUS}`}
              >
                {busy === `backup:${kind.value}` ? "…" : "Backup now"}
              </button>
              <button
                type="button" onClick={() => void act(kind.value, "clean")}
                disabled={busy !== null}
                className={`rounded-[2px] border border-red-500 px-2 py-1 text-[11px] font-bold text-red-600 disabled:opacity-50 ${FOCUS}`}
              >
                {busy === `clean:${kind.value}` ? "…" : "Clean now"}
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-6 rounded-[2px] border border-[var(--ui-line)] bg-white p-5">
        <h2 className="text-[13px] font-bold text-ink">Run history</h2>
        <ul className="mt-3 divide-y divide-[var(--ui-line)]">
          {runs.length === 0 ? <li className="py-3 text-[12px] text-ink/45">No runs yet.</li> : null}
          {runs.map((run) => (
            <li key={run.id} className="flex flex-wrap items-center gap-2 py-2 text-[11px]">
              <span className="rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase" >
                <span className={`rounded-full px-2 py-0.5 ${STATUS[run.status] ?? "bg-ink/[0.06] text-ink/50"}`}>{run.status}</span>
              </span>
              <span className="font-mono text-ink/70">{run.kind}</span>
              <span className="text-ink/45">{run.action} · {run.trigger_type}</span>
              <span className="text-ink/45">{run.rows} rows · {fmtBytes(run.size_bytes)}</span>
              <span className="ml-auto text-ink/45">{fmtTime(run.started_at)}</span>
              {run.error ? <span className="w-full text-red-600">{run.error}</span> : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
