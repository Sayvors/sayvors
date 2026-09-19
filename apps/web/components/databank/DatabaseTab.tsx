"use client";

import { useCallback, useEffect, useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import {
  fetchSourceSchema,
  ingestSourceQuery,
  listDatabaseSources,
  deleteDatabaseSource,
  previewSourceTable,
  runSourceQuery,
  saveDatabaseSource,
  testDatabaseSource,
  type DatabaseConnection,
  type DatabaseSource,
  type QueryResult,
  type TablePreview,
} from "@/lib/api-rag";

const DEFAULT_PORTS = { postgres: 5432, mysql: 3306 } as const;

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-ink/50">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "w-full rounded-xl border-2 border-white bg-ink/[0.03] px-3.5 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40";

export default function DatabaseTab({
  databankId,
  onIngested,
}: {
  databankId: string;
  onIngested: () => void;
}) {
  /* saved sources */
  const [sources, setSources] = useState<DatabaseSource[]>([]);
  const [loadingSources, setLoadingSources] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  /* new connection form */
  const [showForm, setShowForm] = useState(false);
  const [connName, setConnName] = useState("");
  const [dbType, setDbType] = useState<"postgres" | "mysql">("postgres");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("");
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("postgres");
  const [password, setPassword] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; version?: string | null; error?: string | null } | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  /* schema + query lab */
  const [tables, setTables] = useState<{ name: string; columns: number }[]>([]);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [preview, setPreview] = useState<TablePreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [sql, setSql] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [ingestName, setIngestName] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshSources = useCallback(async () => {
    setLoadingSources(true);
    try {
      const data = await listDatabaseSources(databankId);
      setSources(data.sources ?? []);
      if (data.sources?.length && !selectedId) setSelectedId(data.sources[0].id);
    } catch {
      /* backend down — empty state renders */
    } finally {
      setLoadingSources(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [databankId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial source list load on mount
    refreshSources();
  }, [refreshSources]);

  const selected = sources.find((s) => s.id === selectedId) ?? null;

  const loadSchema = useCallback(async () => {
    if (!selected) return;
    setLoadingSchema(true);
    setTables([]);
    setPreview(null);
    try {
      const data = await fetchSourceSchema(databankId, selected.id);
      setTables(data.tables ?? []);
    } catch (e) {
      setQueryError(e instanceof Error ? e.message : "Could not load schema.");
    } finally {
      setLoadingSchema(false);
    }
  }, [databankId, selected]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset lab state on source switch
    setResult(null);
    setQueryError(null);
    setPreview(null);
    setSql("");
    if (selected) loadSchema();
    else setTables([]);
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  function buildConn(): DatabaseConnection {
    return {
      db_type: dbType,
      host: host.trim() || "localhost",
      port: port ? Number(port) : null,
      database: database.trim(),
      username: username.trim(),
      password,
    };
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    setFormError(null);
    try {
      const res = await testDatabaseSource(databankId, buildConn());
      setTestResult(res);
    } catch (e) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : "Connection failed." });
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    if (!connName.trim() || !database.trim() || !username.trim()) {
      setFormError("Name, database and username are required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const saved = await saveDatabaseSource(databankId, { ...buildConn(), name: connName.trim() });
      setSources((prev) => [saved, ...prev]);
      setSelectedId(saved.id);
      setShowForm(false);
      setConnName("");
      setPassword("");
      setTestResult(null);
      setNotice(`Connected to ${saved.database} — pick a table or run a query.`);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Could not save connection.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteDatabaseSource(databankId, id);
      setSources((prev) => prev.filter((s) => s.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch {
      /* keep row on failure */
    }
  }

  async function handlePreview(table: string) {
    if (!selected) return;
    setLoadingPreview(true);
    setPreview(null);
    setQueryError(null);
    try {
      const data = await previewSourceTable(databankId, selected.id, table, 20);
      setPreview(data);
      setSql(`SELECT * FROM ${table}`);
    } catch (e) {
      setQueryError(e instanceof Error ? e.message : "Preview failed.");
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleRun() {
    if (!selected || !sql.trim()) return;
    setRunning(true);
    setResult(null);
    setQueryError(null);
    try {
      const data = await runSourceQuery(databankId, selected.id, sql, 200);
      setResult(data);
    } catch (e) {
      setQueryError(e instanceof Error ? e.message : "Query failed.");
    } finally {
      setRunning(false);
    }
  }

  async function handleIngest() {
    if (!selected || !sql.trim()) return;
    setIngesting(true);
    setQueryError(null);
    try {
      await ingestSourceQuery(databankId, selected.id, sql, ingestName.trim() || undefined, 500);
      setNotice("Result set queued for embedding — watch the documents list.");
      onIngested();
    } catch (e) {
      setQueryError(e instanceof Error ? e.message : "Ingest failed.");
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-ink">Live databases</p>
          <p className="text-[11px] text-ink/45">
            Connect PostgreSQL or MySQL, browse tables, run read-only queries, ingest results.
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
        >
          {showForm ? "Close" : "+ Connect database"}
        </button>
      </div>

      {notice && (
        <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-[12px] font-medium text-emerald-700">
          {notice}
        </div>
      )}

      {/* New connection form */}
      {showForm && (
        <div className="space-y-3 rounded-xl border-2 border-deep-violet/20 bg-white/70 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Connection name">
              <input value={connName} onChange={(e) => setConnName(e.target.value)} placeholder="e.g. Production Postgres" className={inputCls} />
            </Field>
            <div>
              <span className="mb-1 block text-[11px] font-semibold text-ink/50">Type</span>
              <div className="flex gap-2">
                {(["postgres", "mysql"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => { setDbType(t); setTestResult(null); }}
                    className={`flex-1 rounded-xl px-3 py-2 text-[12px] font-bold transition ${
                      dbType === t ? "bg-deep-violet text-white shadow-md" : "bg-ink/[0.04] text-ink/50 hover:bg-ink/[0.08]"
                    }`}
                  >
                    {t === "postgres" ? "PostgreSQL" : "MySQL"}
                  </button>
                ))}
              </div>
            </div>
            <Field label="Host">
              <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="localhost" className={inputCls} />
            </Field>
            <Field label={`Port (default ${DEFAULT_PORTS[dbType]})`}>
              <input value={port} onChange={(e) => setPort(e.target.value)} placeholder={String(DEFAULT_PORTS[dbType])} inputMode="numeric" className={inputCls} />
            </Field>
            <Field label="Database">
              <input value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="mydb" className={inputCls} />
            </Field>
            <Field label="Username">
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder={dbType === "postgres" ? "postgres" : "root"} className={inputCls} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Password">
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Stored encrypted, never shown again" autoComplete="new-password" className={inputCls} />
              </Field>
            </div>
          </div>

          {testResult && (
            <div role="status" className={`rounded-xl px-3 py-2.5 text-[12px] font-medium ${testResult.ok ? "bg-emerald-50 text-emerald-700" : "bg-coral/[0.07] text-coral"}`}>
              {testResult.ok ? `Connected — ${testResult.version}` : testResult.error}
            </div>
          )}

          <details className="rounded-xl border border-ink/[0.06] bg-ink/[0.02]">
            <summary className="cursor-pointer select-none px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-ink/50 hover:text-ink/70">
              Why connect a live database?
            </summary>
            <div className="space-y-2 border-t border-ink/[0.05] px-3 py-3 text-[12px] text-ink/60">
              <p className="font-bold text-ink">When to use it</p>
              <p>Your knowledge already lives in a database — a product catalog, support tickets, customer records, inventory, or a knowledge base table.</p>
              <p className="mt-1"><span className="text-emerald-600">Use when</span> you want AI answers grounded in live data, not a static snapshot. Queries run against the real database at ask time.</p>
              <p className="mt-0.5"><span className="text-amber-600">Watch out</span> only read-only queries are safe here. Credentials are stored encrypted and never shown again.</p>
              <p className="mt-1"><span className="text-ink/50">vs. files:</span> files are simpler but go stale; a live database stays current without re-uploading.</p>
            </div>
          </details>
          {formError && <p role="alert" className="text-[12px] font-medium text-coral">{formError}</p>}

          <div className="flex gap-2">
            <button
              onClick={handleTest}
              disabled={testing || !database.trim()}
              className="flex items-center gap-2 rounded-xl border-2 border-ink/10 px-4 py-2 text-[12px] font-bold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet disabled:opacity-40"
            >
              {testing && <LogoLoader size={14} />} Test connection
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !testResult?.ok}
              title={!testResult?.ok ? "Test the connection first" : undefined}
              className="flex items-center gap-2 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {saving && <LogoLoader size={14} />} Save connection
            </button>
          </div>
        </div>
      )}

      {/* Saved sources */}
      {loadingSources ? (
        <div className="flex justify-center py-6" aria-hidden>
          <LogoLoader size={32} />
        </div>
      ) : sources.length === 0 && !showForm ? (
        <div className="rounded-xl bg-ink/[0.02] px-4 py-8 text-center">
          <p className="text-[13px] font-semibold text-ink/40">No databases connected</p>
          <p className="mt-1 text-[11px] text-ink/30">Connect PostgreSQL or MySQL to query live data.</p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {sources.map((s) => (
            <div
              key={s.id}
              className={`group flex items-center gap-2 rounded-xl border-2 px-3 py-2 transition ${
                selectedId === s.id ? "border-deep-violet/40 bg-deep-violet/[0.04]" : "border-white bg-white/60 hover:border-ink/10"
              }`}
            >
              <button onClick={() => setSelectedId(s.id)} className="flex items-center gap-2 text-left">
                <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-bold uppercase ${s.db_type === "postgres" ? "bg-sky-100 text-sky-700" : "bg-orange-100 text-orange-700"}`}>
                  {s.db_type === "postgres" ? "PG" : "MySQL"}
                </span>
                <span>
                  <span className="block text-[12px] font-bold text-ink">{s.name}</span>
                  <span className="block text-[10px] text-ink/40">{s.host}/{s.database}</span>
                </span>
              </button>
              <button
                onClick={() => handleDelete(s.id)}
                aria-label={`Remove ${s.name}`}
                className="rounded p-1 text-ink/25 opacity-0 transition hover:text-coral group-hover:opacity-100"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Schema browser + query lab */}
      {selected && (
        <div className="grid gap-4 lg:grid-cols-5">
          <div className="rounded-xl border-2 border-white bg-white/60 p-4 lg:col-span-2">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[12px] font-bold text-ink">Tables</p>
              <button onClick={loadSchema} className="text-[11px] font-semibold text-deep-violet hover:underline">
                Refresh
              </button>
            </div>
            {loadingSchema ? (
              <div className="flex justify-center py-6" aria-hidden>
                <LogoLoader size={28} />
              </div>
            ) : tables.length === 0 ? (
              <p className="py-4 text-center text-[11px] text-ink/35">No tables found or schema not loaded.</p>
            ) : (
              <ul className="max-h-64 space-y-1 overflow-y-auto">
                {tables.map((t) => (
                  <li key={t.name}>
                    <button
                      onClick={() => handlePreview(t.name)}
                      className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[12px] transition hover:bg-deep-violet/[0.05]"
                    >
                      <span className="truncate font-mono font-semibold text-ink/75">{t.name}</span>
                      <span className="shrink-0 text-[10px] text-ink/35">{t.columns} cols</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {loadingPreview && (
              <div className="flex justify-center py-4" aria-hidden>
                <LogoLoader size={24} />
              </div>
            )}
            {preview && !loadingPreview && (
              <div className="mt-3 overflow-x-auto rounded-lg border border-ink/[0.06]">
                <ResultTable columns={preview.columns} rows={preview.rows} />
                {preview.truncated && <p className="px-2 py-1 text-[10px] text-ink/35">Showing first rows only.</p>}
              </div>
            )}
          </div>

          <div className="rounded-xl border-2 border-white bg-white/60 p-4 lg:col-span-3">
            <p className="mb-2 text-[12px] font-bold text-ink">Query lab <span className="font-medium text-ink/35">— read-only (SELECT / WITH)</span></p>
            <textarea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              rows={5}
              spellCheck={false}
              placeholder="SELECT * FROM users LIMIT 50"
              className="w-full resize-y rounded-xl border-2 border-ink/[0.08] bg-ink/[0.02] p-3 font-mono text-[12px] leading-relaxed text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40"
            />
            {queryError && <p role="alert" className="mt-2 break-words text-[12px] font-medium text-coral">{queryError}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                onClick={handleRun}
                disabled={running || !sql.trim()}
                className="flex items-center gap-2 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-40"
              >
                {running && <LogoLoader size={14} />} Run query
              </button>
              <input
                value={ingestName}
                onChange={(e) => setIngestName(e.target.value)}
                placeholder="Snapshot name (optional)"
                className="min-w-0 flex-1 rounded-xl border-2 border-ink/[0.08] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40"
              />
              <button
                onClick={handleIngest}
                disabled={ingesting || !result || result.row_count === 0}
                title="Store the last result set as a document and embed it"
                className="flex items-center gap-2 rounded-xl border-2 border-emerald-200 bg-emerald-50 px-4 py-2 text-[12px] font-bold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-40"
              >
                {ingesting && <LogoLoader size={14} />} Ingest results
              </button>
            </div>
            {result && (
              <div className="mt-3">
                <p className="mb-1 text-[11px] text-ink/45">
                  {result.row_count} row{result.row_count === 1 ? "" : "s"}
                  {result.truncated ? " (truncated)" : ""}
                </p>
                <div className="max-h-72 overflow-auto rounded-lg border border-ink/[0.06]">
                  <ResultTable columns={result.columns} rows={result.rows} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  if (columns.length === 0) return <p className="px-3 py-4 text-center text-[11px] text-ink/35">No rows returned.</p>;
  return (
    <table className="w-full border-collapse text-left text-[11px]">
      <thead className="sticky top-0 bg-ink/[0.04]">
        <tr>
          {columns.map((c) => (
            <th key={c} className="whitespace-nowrap px-2.5 py-1.5 font-mono font-bold text-ink/60">{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-ink/[0.04] odd:bg-white/40">
            {r.map((cell, j) => (
              <td key={j} className="max-w-[240px] truncate px-2.5 py-1.5 font-mono text-ink/75" title={cell === null || cell === undefined ? "NULL" : String(cell)}>
                {cell === null || cell === undefined ? <span className="italic text-ink/30">NULL</span> : String(cell)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
