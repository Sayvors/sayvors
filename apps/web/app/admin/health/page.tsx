"use client";

import { useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";
import {
  ErrorState,
  PageHeader,
  Panel,
  Pill,
  SectionTitle,
  Table,
  TableScroll,
  Td,
  Th,
} from "../admin-ui";

interface HealthService {
  name: string;
  kind: string;
  ok: boolean;
  latency_ms: number;
  detail: string;
  enabled: boolean;
  key_source: string;
}
interface HealthFailure {
  source: string;
  type: string;
  message: string;
  at: string | null;
}
interface Health {
  status: string;
  checked_at: string | null;
  uptime_seconds: number;
  services: HealthService[];
  recent_failures: HealthFailure[];
}

export default function AdminHealthPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    adminFetch<Health>("/api/v1/admin/health")
      .then(setHealth)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load health."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading && !health) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  const up = (health?.uptime_seconds ?? 0);
  const uptime = up > 86400
    ? `${Math.floor(up / 86400)}d ${Math.floor((up % 86400) / 3600)}h`
    : `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m`;

  return (
    <div className="admin-ui">
      <PageHeader
        title="Health"
        lede="Live dependency checks."
        actions={
          <button
            onClick={() => void load()}
            disabled={loading}
            aria-busy={loading}
            className="admin-btn border border-ink/10 text-ink/65 hover:bg-ink/[0.04]"
          >
            {loading ? "Checking…" : "Re-check now"}
          </button>
        }
      />
      <div className="mb-[var(--ad-m)] flex flex-wrap items-center gap-[var(--ad-xs)]">
        <Pill tone={health?.status === "ok" ? "ok" : "bad"}>
          {health?.status ?? "unknown"}
        </Pill>
        <span className="text-admin-base text-ink/55">uptime {uptime}</span>
      </div>
      {error && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Health unavailable" detail={error} onRetry={() => void load()} />
        </div>
      )}

      <TableScroll>
        <Table minWidth={720}>
          <thead>
            <tr className="border-b border-ink/[0.06]">
              <Th>Service</Th>
              <Th>Kind</Th>
              <Th>State</Th>
              <Th align="right">Latency</Th>
              <Th>Detail</Th>
            </tr>
          </thead>
          <tbody>
            {(health?.services ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-[var(--ad-s)] py-[var(--ad-m)] text-center text-admin-base text-ink/45">
                  No services reported.
                </td>
              </tr>
            )}
            {(health?.services ?? []).map((s) => (
              <tr key={s.name} className="border-b border-ink/[0.04]">
                <Td className="font-semibold text-ink">{s.name}</Td>
                <Td className="text-ink/55">{s.kind}</Td>
                <Td>
                  <Pill tone={s.ok ? "ok" : "bad"}>{s.ok ? "UP" : "DOWN"}</Pill>
                  {!s.enabled && <span className="ml-[var(--ad-2xs)] text-admin-micro text-ink/40">(disabled)</span>}
                  {s.key_source && s.key_source !== "none" && (
                    <span className="ml-[var(--ad-2xs)] text-admin-micro text-ink/40">key: {s.key_source}</span>
                  )}
                </Td>
                <Td align="right" className="text-ink/55">{s.latency_ms ? `${s.latency_ms}ms` : "—"}</Td>
                <Td className="max-w-xs truncate text-ink/50" title={s.detail}>{s.detail || "—"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </TableScroll>

      <Panel className="mt-[var(--ad-m)]">
        <SectionTitle>Recent failures</SectionTitle>
        {(health?.recent_failures ?? []).length === 0 ? (
          <p className="text-admin-base font-medium text-emerald-700">None recorded.</p>
        ) : (
          <ul className="space-y-[var(--ad-2xs)]">
            {(health?.recent_failures ?? []).map((f, i) => (
              <li key={i} className="flex items-start gap-[var(--ad-2xs)] text-admin-base">
                <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-coral" aria-hidden />
                <span>
                  <span className="font-semibold text-ink">{f.source}</span> <span className="text-ink/45">({f.type})</span>
                  {f.message && <span className="block text-ink/60">{f.message.slice(0, 160)}</span>}
                  {f.at && <span className="block text-admin-micro text-ink/40">{new Date(f.at).toLocaleString()}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
