"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import LogoLoader from "@/components/LogoLoader";
import LocationMultiSelect, { type MultiSelectCopy } from "@/components/LocationMultiSelect";

import {
  ALL_BRANCHES,
  groupLiveCount,
  groupTargets,
  groupValue,
  parseGroupValue,
  useLocationGroups,
  type LocationGroup,
} from "@/lib/location-groups";

type Channel = { id: string; display_name: string | null; listing_id?: string | null };
type Service = { id: string; channel_id: string; name: string; category: string; description: string | null; is_offered: boolean; source: string };

type ServicesCopy = ReturnType<typeof useI18n>["t"]["dashboard"]["services"];

export default function ServicesPage() {
  const { t } = useI18n();
  const copy = t.dashboard.services;
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [name, setName] = useState("");
  // "Custom" is stored data (models.py default), and source "custom" is the
  // wire value the API filters on — both stay English regardless of locale.
  const [category, setCategory] = useState("Custom");
  const [description, setDescription] = useState("");
  // Bulk add: every checked branch gets the service (skip-dup by name).
  const [addLocIds, setAddLocIds] = useState<string[]>([]);

  const { groups } = useLocationGroups();
  // Groups key on Localith listing_id; this page keys on channel id.
  const listingMap: Record<string, string> = Object.fromEntries(
    channels.filter((c) => c.listing_id).map((c) => [c.listing_id as string, c.id]),
  );
  const selectedGroupId = parseGroupValue(selectedId);
  const selectedGroup = selectedGroupId ? groups.find((g) => g.id === selectedGroupId) ?? null : null;
  const groupChannelIds = groupTargets(selectedGroup, listingMap, channels.map((c) => c.id));

  const isAll = selectedId === ALL_BRANCHES || selectedGroup !== null;
  const scopeIds = selectedGroup ? groupChannelIds : channels.map((c) => c.id);
  const branchNames: Record<string, string> = Object.fromEntries(channels.map((c) => [c.id, c.display_name || copy.unnamedLocation]));
  const toggleLoc = (id: string) =>
    setAddLocIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  const selectAllLocs = () =>
    setAddLocIds((prev) => prev.length === scopeIds.length && scopeIds.length > 0 ? [] : scopeIds);
  // Group ticks add to the current selection so a group plus one extra
  // branch still works, matching the Posts picker.
  const selectGroupLocs = (channelIds: string[]) =>
    setAddLocIds((prev) => {
      const allOn = channelIds.every((id) => prev.includes(id));
      return allOn ? prev.filter((id) => !channelIds.includes(id)) : [...new Set([...prev, ...channelIds])];
    });
  // Groups for the picker need channel IDs, resolved through listing_id.
  const pickerGroups = groups
    .map((g) => ({ id: g.id, name: g.name, memberIds: groupTargets(g, listingMap, channels.map((c) => c.id)) }))
    .filter((g) => g.memberIds.length > 0);
  // Entering All-branches (or a group) view defaults to its members — the bulk case.
  const onScopeChange = (id: string) => {
    setSelectedId(id);
    const gid = parseGroupValue(id);
    const g = gid ? groups.find((x) => x.id === gid) ?? null : null;
    setAddLocIds(g ? groupTargets(g, listingMap, channels.map((c) => c.id)) : id === ALL_BRANCHES ? channels.map((c) => c.id) : [id].filter(Boolean));
  };

  useEffect(() => {
    async function load() {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const google = (data.channels ?? []).filter((channel: Channel & { platform: string }) => channel.platform === "google_reviews");
        setChannels(google);
        setSelectedId(google.length ? ALL_BRANCHES : "");
        setAddLocIds(google.map((c: Channel) => c.id));
      } catch (error) { setMessage(error instanceof Error ? error.message : copy.errLoadChannels); }
      finally { setLoading(false); }
    }
    void load();
    // Runs once on mount; `copy` is only read for the error fallback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadServices(scopeId: string, list: Channel[], groupIds?: string[]) {
    const targets =
      scopeId === ALL_BRANCHES
        ? list
        : groupIds
          ? list.filter((c) => groupIds.includes(c.id))
          : list.filter((c) => c.id === scopeId);
    if (targets.length === 0) { setServices([]); return; }
    try {
      const lists = await Promise.all(targets.map(async (c) => {
        try { const data = await apiFetch(`/api/v1/channels/${c.id}/services`); return (data.services ?? []) as Service[]; }
        catch { return [] as Service[]; }
      }));
      setServices(lists.flat());
    }
    catch (error) { setMessage(error instanceof Error ? error.message : copy.errLoadServices); }
  }

  // `copy` is a fresh object each render, so it is deliberately not a dependency;
  // it is only read for the error fallback above.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  // Joined into a string so the effect keys on the group's resolved members
  // (which arrive after mount) rather than on a fresh array each render.
  const groupChannelKey = groupChannelIds.join(",");
  useEffect(() => {
    void loadServices(selectedId, channels, selectedGroup ? groupChannelKey.split(",").filter(Boolean) : undefined);
  }, [selectedId, channels, selectedGroup, groupChannelKey]);

  async function addService() {
    const targets = (isAll ? addLocIds : [selectedId]).filter(Boolean);
    if (!name.trim() || targets.length === 0) return;
    setSaving(true); setMessage(null);
    const trimmed = name.trim().toLowerCase();
    let ok = 0;
    let skipped = 0;
    let failed = 0;
    let firstErr = "";
    for (const chId of targets) {
      try {
        // Skip branches that already have this service (name, case-insensitive)
        // so re-saving never twins rows.
        let existing: Service[] = [];
        try {
          const data = await apiFetch(`/api/v1/channels/${chId}/services`);
          existing = (data.services ?? []) as Service[];
        } catch { /* treat as empty — add will decide */ }
        if (existing.some((s) => s.name.trim().toLowerCase() === trimmed)) {
          skipped += 1;
          continue;
        }
        await apiFetch(`/api/v1/channels/${chId}/services`, {
          method: "POST",
          body: JSON.stringify({ name: name.trim(), category: category.trim() || "Custom", description: description.trim() || null, source: "custom", is_offered: true }),
        });
        ok += 1;
      } catch (error) {
        failed += 1;
        if (!firstErr) firstErr = error instanceof Error ? error.message.slice(0, 140) : copy.errRequest;
      }
    }
    await loadServices(selectedId, channels, selectedGroup ? groupChannelIds : undefined);
    setName("");
    setDescription("");
    const n = targets.length;
    if (n > 1) {
      const parts = [copy.detail.replace("{ok}", String(ok)).replace("{total}", String(n))];
      if (skipped) parts.push(copy.detailSkipped.replace("{count}", String(skipped)));
      if (failed) parts.push(copy.detailFailed.replace("{count}", String(failed)));
      setMessage(
        failed === 0 && skipped === 0
          ? copy.savedAll.replace("{count}", String(n))
          : copy.savedPartial
              .replace("{detail}", parts.join(copy.listSeparator))
              .replace("{err}", firstErr ? ` — ${firstErr}` : "")
      );
    } else if (skipped) {
      setMessage(copy.alreadyThere);
    } else if (failed) {
      setMessage(`${copy.errSave} ${firstErr}`);
    } else {
      setMessage(copy.savedOne);
    }
    setSaving(false);
  }

  async function toggleService(service: Service) {
    try { const updated = await apiFetch(`/api/v1/channels/${service.channel_id}/services/${service.id}`, { method: "PUT", body: JSON.stringify({ is_offered: !service.is_offered }) }); setServices((current) => current.map((item) => item.id === updated.id ? updated : item)); }
    catch (error) { setMessage(error instanceof Error ? error.message : copy.errUpdate); }
  }

  async function removeService(service: Service) {
    try { await apiFetch(`/api/v1/channels/${service.channel_id}/services/${service.id}`, { method: "DELETE" }); setServices((current) => current.filter((item) => item.id !== service.id)); }
    catch (error) { setMessage(error instanceof Error ? error.message : copy.errDelete); }
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f4f1ff] p-4 sm:p-6">
      <div className="mx-auto max-w-4xl space-y-5">
            <PageHeader connected={channels.length > 0} copy={copy} />
            {loading ? (
              <div className="flex justify-center rounded-3xl bg-white/70 py-24"><LogoLoader size={34} /></div>
            ) : (
              <>
                <LocationPicker
                  selectedId={selectedId}
                  channels={channels}
                  onChange={onScopeChange}
                  copy={copy}
                  groups={groups}
                  listingMap={listingMap}
                />
                <StatsRow services={services} copy={copy} />
                <AddServiceForm
                  name={name} category={category} description={description}
                  onName={setName} onCategory={setCategory} onDescription={setDescription}
                  isAll={isAll} channels={channels}
                  selectedIds={isAll ? addLocIds : [selectedId].filter(Boolean)}
                  onToggleLoc={toggleLoc} onSelectAll={selectAllLocs}
                  onSelectGroup={selectGroupLocs} groups={pickerGroups} groupsLabel="Groups"
                  saving={saving}
                  canSave={!!name.trim() && (isAll ? addLocIds.length > 0 : !!selectedId)}
                  onAdd={() => void addService()}
                  copy={copy}
                  multiSelectCopy={t.dashboard.multiSelect}
                />
                <ServiceGroup title={copy.googleGroup} source="google" services={services.filter((service) => service.source === "google")} onToggle={toggleService} onDelete={removeService} branchNames={isAll ? branchNames : undefined} copy={copy} />
                <ServiceGroup title={copy.customGroup} source="custom" services={services.filter((service) => service.source !== "google")} onToggle={toggleService} onDelete={removeService} branchNames={isAll ? branchNames : undefined} copy={copy} />
              </>
            )}
        {message && <div className="rounded-xl border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">{message}</div>}
      </div>
    </div>
  );
}

function PageHeader({ connected, copy }: { connected: boolean; copy: ServicesCopy }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-[22px] font-bold text-ink">{copy.title}</h1>
        <p className="mt-1 text-[13px] text-ink/55">{copy.subtitle}</p>
      </div>
      <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${connected ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
        {connected ? copy.googleConnected : copy.googleNotConnected}
      </span>
    </div>
  );
}

function LocationPicker({ selectedId, channels, onChange, copy, groups, listingMap }: {
  selectedId: string;
  channels: Channel[];
  onChange: (id: string) => void;
  copy: ServicesCopy;
  groups: LocationGroup[];
  listingMap: Record<string, string>;
}) {
  return (
    <div className="rounded-3xl border border-white bg-white/80 p-5">
      <label className="block text-[11px] font-bold text-ink/55">
        {copy.locationLabel}
        <select value={selectedId} onChange={(event) => onChange(event.target.value)} className="input-field mt-2">
          <option value="">{copy.noLocationData}</option>
          {channels.length > 0 && <option value={ALL_BRANCHES}>{copy.allBranches.replace("{count}", String(channels.length))}</option>}
          {groups
            .map((g) => ({ id: g.id, name: g.name, n: groupLiveCount(g, listingMap) }))
            .filter((g) => g.n > 0)
            .map((g) => (
              <option key={g.id} value={groupValue(g.id)}>
                {g.name} ({g.n})
              </option>
            ))}
          {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || copy.unnamedLocation}</option>)}
        </select>
      </label>
    </div>
  );
}

function StatsRow({ services, copy }: { services: Service[]; copy: ServicesCopy }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Stat label={copy.statTotal} value={services.length} />
      <Stat label={copy.statOffered} value={services.filter((service) => service.is_offered).length} />
      <Stat label={copy.statCustom} value={services.filter((service) => service.source === "custom").length} />
    </div>
  );
}

function AddServiceForm({ name, category, description, onName, onCategory, onDescription, isAll, channels, selectedIds, onToggleLoc, onSelectAll, onSelectGroup, groups, groupsLabel, saving, canSave, onAdd, copy, multiSelectCopy }: {
  name: string; category: string; description: string;
  onName: (v: string) => void; onCategory: (v: string) => void; onDescription: (v: string) => void;
  isAll: boolean; channels: Channel[];
  selectedIds: string[]; onToggleLoc: (id: string) => void; onSelectAll: () => void;
  onSelectGroup: (ids: string[]) => void; groups: { id: string; name: string; memberIds: string[] }[]; groupsLabel: string;
  saving: boolean; canSave: boolean;
  onAdd: () => void;
  copy: ServicesCopy;
  multiSelectCopy: MultiSelectCopy;
}) {
  return (
    <div className="rounded-3xl border border-white bg-white/80 p-5">
      <h2 className="text-[15px] font-bold text-ink">{copy.addService}</h2>
      <p className="mt-1 text-[11px] text-ink/45">
        {isAll ? copy.addServiceAllHint : copy.addServiceSingleHint}
      </p>
      {isAll && channels.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-bold text-ink/55">{copy.addToBranches}</p>
          <span className="mt-2 block">
            <LocationMultiSelect
              locations={channels.map((c) => ({ id: c.id, name: c.display_name || copy.unnamedLocation }))}
              selectedIds={selectedIds}
              onToggle={onToggleLoc}
              onSelectAll={onSelectAll}
              onSelectGroup={onSelectGroup}
              groups={groups}
              groupsLabel={groupsLabel}
              copy={multiSelectCopy}
            />
          </span>
        </div>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <input value={name} onChange={(event) => onName(event.target.value)} placeholder={copy.namePlaceholder} className="input-field" />
        <input value={category} onChange={(event) => onCategory(event.target.value)} placeholder={copy.categoryPlaceholder} className="input-field" />
        <input value={description} onChange={(event) => onDescription(event.target.value)} placeholder={copy.descriptionPlaceholder} className="input-field" />
      </div>
      <p className="mt-2 text-[11px] text-ink/40">{copy.aiHint}</p>
      <button onClick={onAdd} disabled={saving || !canSave} className="mt-4 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white disabled:opacity-40">
        {saving
          ? copy.saving
          : selectedIds.length > 1
            ? copy.addToBranchesBtn.replace("{count}", String(selectedIds.length))
            : copy.addService}
      </button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-2xl border border-white bg-white/80 p-4"><div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{label}</div><div className="mt-2 text-[22px] font-bold text-ink">{value}</div></div>;
}

function ServiceGroup({ title, source, services, onToggle, onDelete, branchNames, copy }: { title: string; source: "google" | "custom"; services: Service[]; onToggle: (service: Service) => Promise<void>; onDelete: (service: Service) => Promise<void>; branchNames?: Record<string, string>; copy: ServicesCopy }) {
  return <section className="overflow-hidden rounded-3xl border border-white bg-white/80"><header className="flex items-center justify-between border-b border-ink/[0.05] px-4 py-3"><div><h2 className="text-[14px] font-bold text-ink">{title}</h2><p className="mt-0.5 text-[11px] text-ink/40">{source === "google" ? copy.googleGroupSub : copy.customGroupSub}</p></div><span className="rounded-full bg-ink/[0.04] px-2.5 py-1 text-[10px] font-semibold text-ink/45">{services.length}</span></header>{services.length === 0 ? <div className="border-dashed px-4 py-8 text-center text-[12px] text-ink/35">{copy.noServiceData}</div> : <div className="divide-y divide-ink/[0.04]">{services.map((service) => <div key={service.id} className="flex items-center gap-3 px-4 py-3"><button onClick={() => void onToggle(service)} className={`h-5 w-5 shrink-0 rounded-md border-2 ${service.is_offered ? "border-deep-violet bg-deep-violet" : "border-ink/20"}`} aria-label={copy.toggleOffered}>{service.is_offered && <span className="text-[11px] text-white">✓</span>}</button><div className="min-w-0 flex-1"><div className="text-[13px] font-bold text-ink">{service.name}</div><div className="text-[11px] text-ink/45">{branchNames?.[service.channel_id] ? `${branchNames[service.channel_id]} · ` : ""}{service.category} · {service.is_offered ? copy.offered : copy.notOffered}{service.description ? ` · ${service.description}` : ""}</div></div><button onClick={() => void onDelete(service)} className="shrink-0 text-[11px] font-semibold text-red-500">{copy.delete}</button></div>)}</div>}</section>;
}
