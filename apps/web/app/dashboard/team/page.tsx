"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { resolveMediaUrl } from "@/lib/media-url";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type TeamDict = Dict["team"];

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

/* Team management — members, roles and per-channel access. */

interface TeamRoleOption { id: string; name: string; is_system?: boolean; permissions?: string[] }
interface TeamChannelOption { id: string; platform: string; name?: string | null; status?: string }
interface TeamMemberRow {
  id: string | null;
  email: string;
  name?: string;
  role_name?: string;
  role_id?: string | null;
  is_owner?: boolean;
  status?: string;
  invited_at?: string | null;
  accepted_at?: string | null;
  channels?: Record<string, string> | null;
  avatar_url?: string | null;
}
interface TeamContextInfo {
  business_name?: string | null;
  role_name?: string;
  is_owner?: boolean;
  member_id?: string | null;
  permissions?: string[];
}
interface CatalogArea {
  area: string;
  label: string;
  actions: { permission: string; action: string; label: string }[];
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LEVELS = ["none", "view", "edit"] as const;
type Level = (typeof LEVELS)[number];
/** "No override stored" — the member inherits whatever the role allows.
 * Deliberately distinct from "none", which is a stored denial. */
const FOLLOW = "follow" as const;
type Access = Level | typeof FOLLOW;

function errText(e: unknown, fallback?: string): string {
  if (e instanceof Error) {
    try {
      const parsed = JSON.parse(e.message);
      const d = parsed.detail;
      if (typeof d === "string") return d;
      if (d && typeof d === "object" && typeof d.message === "string") return d.message;
    } catch {
      /* not JSON — fall through */
    }
    return e.message;
  }
  return fallback ?? "Request failed";
}

function shortDate(iso: string | null | undefined, dateLocale?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(dateLocale, { month: "short", day: "numeric" });
}

/*
 * Three colours only: #000000 ink, #FFFFFF surfaces, #F5F5F5 page. Depth
 * comes from hairlines, not shadows - see the .ui-* primitives in globals.css.
 */
const UI_BTN = "ui-btn rounded-lg text-[12px] font-bold";

const FIELD =
  "ui-input w-full bg-[var(--ui-surface)] px-4 py-3 text-[13px] font-medium text-[var(--ui-ink)] placeholder:text-[var(--ui-ink-2)]";
const BTN = `${UI_BTN} px-5 py-3`;
const BTN_PRIMARY = `${BTN} bg-[var(--ui-ink)] text-[var(--ui-on-ink)]`;
const BTN_GHOST = `${BTN} bg-[var(--ui-surface)] text-[var(--ui-ink)]`;
const BTN_DANGER = `${UI_BTN.replace("ui-btn", "ui-btn-danger")} bg-[var(--ui-sunken)] px-5 py-3 text-[var(--ui-ink)]`;

function StatusBadge({ status }: { status?: string }) {
  const { t } = useI18n();
  const tm = t.team;
  const s = (status || "active").toLowerCase();
  // Three colours only, so status is carried by the word and by weight, never
  // by a hue: "Suspended" in bold black reads differently from "Active"
  // without inventing a fifth colour.
  const label = tm.status[s as keyof typeof tm.status] ?? (s.charAt(0).toUpperCase() + s.slice(1));
  const strong = s === "suspended" || s === "expired";
  return (
    <span
      className={`rounded-[8px] px-3 py-1 text-[12px] ${
        strong ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]" : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
      }`}
    >
      {label}
    </span>
  );
}

/** Connection state of a channel — quiet enough to sit next to the name. */
function StatusDot({ status }: { status?: string }) {
  const { t } = useI18n();
  const tm = t.team;
  const s = (status || "active").toLowerCase();
  // The dot is decoration; the state is always spelled out, because a colour
  // dot alone tells a screen-reader user nothing.
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className={`inline-block h-1.5 w-1.5 rounded-full ${s === "active" ? "bg-[var(--ui-ink)]" : "bg-[var(--ui-ink-2)]"}`}
      />
      {s !== "active" ? <span className="font-semibold">{tm.status[s as keyof typeof tm.status] ?? s}</span> : <span className="sr-only">{s}</span>}
    </span>
  );
}

function RoleBadge({ name, isOwner }: { name?: string; isOwner?: boolean }) {
  const { t } = useI18n();
  const tm = t.team;
  if (isOwner || name === "Owner") {
    return <span className="ui-chip shrink-0 px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)]">{tm.roleOwner}</span>;
  }
  return <span className="ui-chip shrink-0 px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)]">{name || tm.roleNone}</span>;
}

function Initial({
  label,
  owner,
  avatarUrl,
}: {
  label: string;
  owner?: boolean;
  avatarUrl?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [avatarUrl]);
  const src = resolveMediaUrl(avatarUrl);

  return (
    <div
      className={`flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full text-[12px] font-bold ${
        owner
          ? "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
          : "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
      }`}
    >
      {src && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- runtime provider/upload URL
        <img
          src={src}
          alt=""
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        (label || "?").trim().charAt(0).toUpperCase()
      )}
    </div>
  );
}

function areaOf(permission: string): string {
  const i = permission.indexOf(".");
  return i === -1 ? permission : permission.slice(0, i);
}

function roleAreas(role?: TeamRoleOption): string[] {
  const perms = role?.permissions || [];
  return Array.from(new Set(perms.map(areaOf)));
}

function areaLabels(areas: string[], catalog: CatalogArea[]): string[] {
  const byArea = new Map(catalog.map((a) => [a.area, a.label]));
  return areas.map((a) => byArea.get(a) || a.charAt(0).toUpperCase() + a.slice(1));
}

function RoleSummary({ role, catalog, membersCount, compact }: { role: TeamRoleOption; catalog: CatalogArea[]; membersCount: number; compact?: boolean }) {
  const { t, locale } = useI18n();
  const tm = t.team;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const perms = role.permissions || [];
  const labels = areaLabels(roleAreas(role), catalog);
  if (perms.length === 0) {
    return <p className="text-[12px] text-[var(--ui-ink-2)]">{tm.noPerms}</p>;
  }
  // One line of text, not a cloud of chips: chips wrapped into ragged rows and
  // collided with the count beside them.
  const cap = compact ? 4 : 7;
  const shown = labels.slice(0, cap);
  const hidden = labels.length - shown.length;
  return (
    <p className="mt-1 text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
      <span className="font-semibold text-[var(--ui-ink)]">
        {perms.length === 1 ? tm.permOne : fill(tm.permN, { n: fmt(perms.length) })}
      </span>
      {membersCount > 0 && ` · ${membersCount === 1 ? tm.memberOne : fill(tm.memberN, { n: fmt(membersCount) })}`}
      <span className="block">
        {shown.join(", ")}
        {hidden > 0 && ` ${fill(tm.moreN, { n: fmt(hidden) })}`}
      </span>
    </p>
  );
}

/**
 * Roles as a matrix: one row per role, one column per permission area, and
 * each cell reads "granted / total" for that area. Comparing two roles used to
 * mean reading two chip clouds; now the eye just scans a column.
 */
function PermissionMatrix({
  roles, catalog, membersCount, canManage, onEdit, onDelete, pending,
}: {
  roles: TeamRoleOption[];
  catalog: CatalogArea[];
  membersCount: (id: string) => number;
  canManage: boolean;
  onEdit: (r: TeamRoleOption) => void;
  onDelete: (r: TeamRoleOption) => void;
  pending: Record<string, boolean>;
}) {
  const { t, locale } = useI18n();
  const tm = t.team;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  // Hide areas the catalog does not offer, and never show billing: nothing
  // enforces those, so they would be checkboxes that do nothing.
  const areas = catalog
    .filter((a) => a.area !== "billing" && a.actions.length > 0)
    .map((a) => ({
      area: a.area,
      label: tm.areas[a.area as keyof typeof tm.areas] || a.label,
      actions: a.actions.map((act) => act.permission),
    }));

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse text-left">
        <caption className="sr-only">
          {tm.matrixCaption}
        </caption>
        <thead>
          <tr className="border-b border-[var(--ui-line)]">
            <th scope="col" className="pb-2 pr-4 text-[12px] font-semibold text-[var(--ui-ink-2)]">{tm.roleCol}</th>
            {areas.map((a) => (
              <th
                key={a.area}
                scope="col"
                className="pb-2 pr-3 text-[12px] font-semibold whitespace-nowrap text-[var(--ui-ink-2)]"
              >
                {a.label}
              </th>
            ))}
            <th scope="col" className="pb-2 pr-4 text-[12px] font-semibold whitespace-nowrap text-[var(--ui-ink-2)]">{tm.membersCol}</th>
            {canManage && <th scope="col" className="pb-2 text-[12px] font-semibold text-[var(--ui-ink-2)]"><span className="sr-only">{tm.actionsCol}</span></th>}
          </tr>
        </thead>
        <tbody>
          {roles.map((r) => {
            const perms = new Set(r.permissions || []);
            const inUse = membersCount(r.id);
            return (
              <tr key={r.id} className="border-b border-[var(--ui-line)] last:border-0">
                <th scope="row" className="py-3 pr-4 align-top font-normal">
                  <span className="flex items-center gap-2 whitespace-nowrap">
                    <span className="text-[13px] font-semibold text-[var(--ui-ink)]">{r.name}</span>
                    {r.is_system ? (
                      <span className="ui-chip px-2 py-0.5 text-[11px] font-semibold text-[var(--ui-ink-2)]">{tm.builtIn}</span>
                    ) : (
                      <span className="ui-chip px-2 py-0.5 text-[11px] font-semibold text-[var(--ui-ink-2)]">{tm.custom}</span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-[12px] tabular-nums text-[var(--ui-ink-2)]">
                    {perms.size === 1 ? tm.permOne : fill(tm.permN, { n: fmt(perms.size) })}
                  </span>
                </th>
                {areas.map((a) => {
                  const granted = a.actions.filter((p) => perms.has(p));
                  const total = a.actions.length;
                  const full = granted.length === total;
                  const none = granted.length === 0;
                  const detail = `${granted.join(", ") || tm.phrases.none}`;
                  return (
                    <td
                      key={a.area}
                      className="py-3 pr-3 align-top text-[12px] tabular-nums"
                      title={detail}
                    >
                      <span
                        className={
                          none
                            ? "text-[var(--ui-ink-2)]"
                            : full
                              ? "font-bold text-[var(--ui-ink)]"
                              : "text-[var(--ui-ink)]"
                        }
                      >
                        {none ? "—" : `${fmt(granted.length)}/${fmt(total)}`}
                      </span>
                      <span className="sr-only">
                        {fill(tm.srDetail, { label: a.label, detail, total: fmt(total) })}
                      </span>
                    </td>
                  );
                })}
                <td className="py-3 pr-4 align-top text-[12px] text-[var(--ui-ink-2)]">
                  {inUse > 0 ? `${fmt(inUse)}` : <span className="text-[var(--ui-ink-2)]">—</span>}
                </td>
                {canManage && (
                  <td className="py-3 text-right align-top">
                    <span className="inline-flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => onEdit(r)}
                        className={`${BTN} px-4 py-2 text-[12px] font-semibold`}
                      >
                        {tm.editBtn}
                      </button>
                      {!r.is_system && (
                        <ConfirmButton
                          label={tm.deleteBtn}
                          confirmLabel={tm.confirmDelete}
                          pending={pending[`deleterole:${r.id}`]}
                          onConfirm={() => onDelete(r)}
                          className={`${BTN_DANGER} px-4 py-2`}
                        />
                      )}
                    </span>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-3 text-[12px] text-[var(--ui-ink-2)]">
        {tm.legend}
      </p>
    </div>
  );
}

function ConfirmButton({
  label, confirmLabel, pending, onConfirm, className,
}: {
  label: string; confirmLabel: string; pending?: boolean; onConfirm: () => void; className: string;
}) {
  const { t } = useI18n();
  const tm = t.team;
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  if (!armed) {
    return (
      <button type="button" className={className} disabled={pending} onClick={() => setArmed(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        className={className}
        disabled={pending}
        onClick={() => { setArmed(false); onConfirm(); }}
      >
        {pending ? tm.working : confirmLabel}
      </button>
      <button
        type="button"
        className={`${BTN} text-[var(--ui-ink-2)]`}
        disabled={pending}
        onClick={() => setArmed(false)}
      >
        {tm.cancelBtn}
      </button>
    </span>
  );
}

function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[var(--ui-ink)]">
      <span className="h-2.5 w-2.5 animate-spin rounded-full border-2  border-t-[var(--ui-ink)]" aria-hidden />
      {label}
    </span>
  );
}

function ChannelAccess({
  channels, value, roleLabel, roleDefault, pending, onSave,
}: {
  channels: TeamChannelOption[]; value: Record<string, string>; roleLabel: string; roleDefault: Level;
  pending?: boolean; onSave: (levels: Record<string, Level>) => void;
}) {
  const { t } = useI18n();
  const tm = t.team;
  // Seeded from the stored overrides; every other channel inherits the role.
  const [levels, setLevels] = useState<Record<string, Access>>(value as Record<string, Access>);

  // A channel absent from `levels` has no override stored: the member inherits
  // the role. Keep it absent on save so "no override" stays "no override" and
  // the member keeps tracking the role.
  const overrides = (src: Record<string, Access>) =>
    Object.fromEntries(Object.entries(src).filter(([, lvl]) => lvl !== FOLLOW)) as Record<string, Level>;

  const norm = (o: Record<string, string>) =>
    JSON.stringify(Object.entries(o).sort(([a], [b]) => a.localeCompare(b)));
  const dirty = norm(overrides(levels)) !== norm(value);

  const setAll = (lvl: Access) => {
    if (lvl === FOLLOW) {
      setLevels({});
      return;
    }
    setLevels(Object.fromEntries(channels.map((ch) => [ch.id, lvl])));
  };

  if (channels.length === 0) {
    return <p className="text-[11px] text-[var(--ui-ink-2)]">{tm.noChannels}</p>;
  }

  return (
    <div className="mt-3 rounded-[8px] bg-[var(--ui-sunken)] p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-semibold text-[var(--ui-ink-2)]">{tm.perChannel}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            className={`${BTN} text-[var(--ui-ink-2)]`}
            onClick={() => setAll(FOLLOW)}
          >
            {tm.allFollow}
          </button>
          {LEVELS.map((lvl) => (
            <button key={lvl} type="button" className={`${BTN} text-[var(--ui-ink-2)]`} onClick={() => setAll(lvl)}>
              {fill(tm.allLevel, { level: tm.levels[lvl] })}
            </button>
          ))}
        </div>
      </div>
      <p className="mb-2 text-[12px] text-[var(--ui-ink-2)]">
        {fill(tm.roleAllows, { role: roleLabel, level: tm.phrases[roleDefault] })}
      </p>
      <div className="space-y-1">
        {channels.map((ch) => {
          const lvl: Access = levels[ch.id] ?? FOLLOW;
          const effective: Access = lvl === FOLLOW ? roleDefault : lvl;
          const name = ch.name || ch.platform;
          const label = platformLabel(ch.platform);
          return (
            <div
              key={ch.id}
              title={`${name} · ${label} · ${lvl === FOLLOW ? fill(tm.followRole, { level: tm.levels[roleDefault] }) : tm.levels[effective as Level]}`}
              className="flex flex-wrap items-start gap-3 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3 transition hover:bg-[var(--ui-sunken)]"
            >
              {/* Mark and name travel together so a wrap never orphans the mark. */}
              <div className="flex min-w-[11rem] flex-1 items-start gap-3">
                <PlatformMark platform={ch.platform} size={18} className="mt-0.5" />
                {/* Full name, wrapped: several channels can share a display name and
                    only the provider tells them apart. */}
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] leading-snug font-bold break-words text-[var(--ui-ink)]">{name}</p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-[12px] text-[var(--ui-ink-2)]">
                    <span>{label}</span>
                    <StatusDot status={ch.status} />
                  </p>
                </div>
              </div>
              <select
                value={lvl}
                aria-label={fill(tm.accessFor, { name, label })}
                onChange={(e) => setLevels({ ...levels, [ch.id]: e.target.value as Access })}
                className={`ui-input ml-auto w-full bg-[var(--ui-surface)] px-3 py-3 text-[12px] font-bold sm:w-auto ${
                  lvl === FOLLOW
                    ? "text-[var(--ui-ink-2)]"
                    : "text-[var(--ui-ink)] font-bold"
                }`}
              >
                <option value={FOLLOW}>{fill(tm.followRole, { level: tm.levels[roleDefault] })}</option>
                {LEVELS.map((l) => <option key={l} value={l}>{tm.levels[l]}</option>)}
              </select>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex items-center justify-end gap-2">
        {dirty && <span className="rounded-[8px] bg-[var(--ui-sunken)] px-3 py-1 text-[12px] font-bold text-[var(--ui-ink)]">{tm.unsaved}</span>}
        <button
          type="button"
          className={BTN_PRIMARY}
          disabled={pending || !dirty}
          onClick={() => onSave(overrides(levels))}
        >
          {pending ? tm.saving : tm.saveAccess}
        </button>
      </div>
    </div>
  );
}

function RoleSelect({
  value, roles, catalog, membersCount, onChange, disabled, pending, label, summary = true, className = FIELD,
}: {
  value: string; roles: TeamRoleOption[]; catalog: CatalogArea[];
  membersCount?: (id: string) => number;
  onChange: (id: string) => void; disabled?: boolean; pending?: boolean; label: string;
  summary?: boolean; className?: string;
}) {
  const selected = roles.find((r) => r.id === value);
  const { t, locale } = useI18n();
  const tm = t.team;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  return (
    <div className="min-w-0">
      <select
        value={value}
        aria-label={label}
        disabled={disabled || pending}
        onChange={(e) => onChange(e.target.value)}
        className={`${className} disabled:opacity-60`}
      >
        <option value="">{tm.selectRole}</option>
        {roles.map((r) => {
          const n = (r.permissions || []).length;
          const m = membersCount?.(r.id) ?? 0;
          return (
            <option key={r.id} value={r.id}>
              {r.name} — {n === 1 ? tm.permOne : fill(tm.permN, { n: fmt(n) })}{r.is_system ? ` · ${tm.builtIn}` : ""}{m > 0 ? ` · ${m === 1 ? tm.memberOne : fill(tm.memberN, { n: fmt(m) })}` : ""}
            </option>
          );
        })}
      </select>
      {summary && (selected ? (
        <RoleSummary role={selected} catalog={catalog} membersCount={membersCount?.(selected.id) ?? 0} compact />
      ) : (
        <p className="mt-1 text-[11px] text-[var(--ui-ink-2)]">{tm.pickRoleHint}</p>
      ))}
    </div>
  );
}

function InviteForm({ roles, catalog, members, channels, membersCount, onInvited }: {
  roles: TeamRoleOption[];
  catalog: CatalogArea[];
  members: TeamMemberRow[];
  channels: TeamChannelOption[];
  membersCount: (id: string) => number;
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [channelLevels, setChannelLevels] = useState<Record<string, string>>({});
  const [showChannels, setShowChannels] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const { t, locale } = useI18n();
  const tm = t.team;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);

  const normalized = email.trim().toLowerCase();
  const emailValid = EMAIL_RE.test(normalized);
  const duplicate = normalized ? members.find((m) => m.email.toLowerCase() === normalized) : undefined;
  const canSend = emailValid && !!roleId && !duplicate && !sending;
  const overrideCount = Object.values(channelLevels).filter((v) => v === "view" || v === "edit").length;

  const setAllChannels = (lvl: string) => {
    const next: Record<string, string> = {};
    for (const ch of channels) next[ch.id] = lvl;
    setChannelLevels(next);
  };

  const handleSubmit = async () => {
    setSending(true); setError(""); setSuccess("");
    try {
      const payload = Object.fromEntries(
        Object.entries(channelLevels).filter(([, v]) => v === "view" || v === "edit"),
      );
      const data = await apiFetch("/api/v1/team/invites", {
        method: "POST",
        body: JSON.stringify({ email: normalized, role_id: roleId, channel_levels: payload }),
      });
      setSuccess(fill(tm.inviteSent, { email: data.email || normalized }));
      setEmail(""); setRoleId(""); setChannelLevels({}); setShowChannels(false);
      onInvited();
    } catch (e) {
      setError(errText(e, tm.errFallback));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mt-3 max-w-5xl space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <div>
          <label htmlFor="invite-email" className="text-[11px] font-medium text-[var(--ui-ink-2)]">{tm.emailLabel}</label>
          <input
            id="invite-email"
            type="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setError(""); setSuccess(""); }}
            placeholder="team-member@example.com"
            className={`mt-1 ${FIELD}`}
          />
          {email && !emailValid && <p className="mt-1 text-[12px] font-semibold text-[var(--ui-ink)]">{tm.invalidEmail}</p>}
          {duplicate && (
            <p className="mt-1 text-[12px] font-medium text-[var(--ui-ink-2)]">
              {duplicate.is_owner || duplicate.status === "active"
                ? tm.dupActive
                : tm.dupPending}
            </p>
          )}
        </div>
        <div>
          <span className="text-[11px] font-medium text-[var(--ui-ink-2)]">{tm.roleLabel}</span>
          <div className="mt-1">
            <RoleSelect
              value={roleId}
              roles={roles}
              catalog={catalog}
              membersCount={membersCount}
              onChange={(id) => { setRoleId(id); setError(""); setSuccess(""); }}
              label={tm.roleForInvite}
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2 xl:col-span-1 xl:justify-end">
          <button type="button" onClick={handleSubmit} disabled={!canSend} className={BTN_PRIMARY}>
            {sending ? tm.sending : tm.send}
          </button>
        </div>
      </div>

      {(success || error) && (
        <p
          role="status"
          className={`text-[12px] font-medium ${success ? "text-[var(--ui-ink)]" : "text-[var(--ui-ink)]"}`}
        >
          {success || error}
        </p>
      )}

      {channels.length > 0 && (
        <div className="rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)]">
          <button
            type="button"
            aria-expanded={showChannels}
            onClick={() => setShowChannels((v) => !v)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-[var(--ui-sunken)]"
          >
            <svg viewBox="0 0 12 12" fill="none" className={`h-3 w-3 shrink-0 text-[var(--ui-ink-2)] transition-transform ${showChannels ? "rotate-90" : ""}`} aria-hidden>
              <path d="M4.5 2.5 8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[11px] font-semibold text-[var(--ui-ink-2)]">{tm.perChannelTitle}</span>
            <span className="text-[12px] text-[var(--ui-ink-2)]">{tm.optional}</span>
            <span className="ml-auto text-[12px] font-medium text-[var(--ui-ink-2)]">
              {overrideCount > 0 ? (overrideCount === 1 ? fill(tm.ovrOne, { n: fmt(overrideCount) }) : fill(tm.ovrN, { n: fmt(overrideCount) })) : tm.inherits}
            </span>
          </button>
          {showChannels && (
            <div className="p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-[11px] text-[var(--ui-ink-2)]">{tm.narrowHint}</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  {LEVELS.map((lvl) => (
                    <button key={lvl} type="button" className={`${BTN} text-[var(--ui-ink-2)]`} onClick={() => setAllChannels(lvl)}>
                      {fill(tm.allLevel, { level: tm.levels[lvl] })}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-1">
                {channels.map((ch) => (
                  <div key={ch.id} className="flex items-center justify-between gap-2 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 transition hover:bg-[var(--ui-sunken)]">
                    <span className="truncate text-[11px] text-[var(--ui-ink)]">{ch.name || ch.platform}</span>
                    <select
                      value={channelLevels[ch.id] || "none"}
                      aria-label={fill(tm.accessForShort, { name: ch.name || ch.platform })}
                      onChange={(e) => { setChannelLevels({ ...channelLevels, [ch.id]: e.target.value }); setSuccess(""); }}
                      className="ui-input shrink-0 px-3 py-3 text-[12px] font-semibold capitalize text-[var(--ui-ink)]"
                    >
                      {LEVELS.map((lvl) => <option key={lvl} value={lvl}>{tm.levels[lvl]}</option>)}
                    </select>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RoleBuilder({ editing, catalog, onDone }: { editing: TeamRoleOption | null; catalog: CatalogArea[]; onDone: () => void }) {
  const { t, locale } = useI18n();
  const tm = t.team;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const [name, setName] = useState(editing?.name ?? "");
  const [selected, setSelected] = useState<string[]>(editing?.permissions ?? []);
  const [openAreas, setOpenAreas] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const areas = catalog.filter((a) => a.area !== "billing");
  const isSystem = !!editing?.is_system;

  const selectedSet = new Set(selected);
  const q = query.trim().toLowerCase();
  const visibleAreas = areas
    .map((a) => ({
      ...a,
      actions: q
        ? a.actions.filter(
            (act) =>
              act.label.toLowerCase().includes(q) ||
              act.permission.toLowerCase().includes(q) ||
              a.label.toLowerCase().includes(q),
          )
        : a.actions,
    }))
    .filter((a) => a.actions.length > 0);

  const toggle = (perm: string) => {
    setSuccess(""); setError("");
    setSelected((prev) => (prev.includes(perm) ? prev.filter((p) => p !== perm) : [...prev, perm]));
  };

  const setArea = (area: CatalogArea, on: boolean) => {
    setSuccess(""); setError("");
    const perms = area.actions.map((a) => a.permission);
    setSelected((prev) =>
      on ? Array.from(new Set([...prev, ...perms])) : prev.filter((p) => !perms.includes(p)),
    );
  };

  const canSave = (isSystem || name.trim().length > 0) && selected.length > 0 && !busy;

  const handleSave = async () => {
    setBusy(true); setError(""); setSuccess("");
    try {
      if (editing) {
        const data = await apiFetch(`/api/v1/team/roles/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(
            isSystem ? { permissions: selected } : { name: name.trim(), permissions: selected },
          ),
        });
        setSuccess(fill(tm.roleUpdated, { name: data.name }));
      } else {
        const data = await apiFetch("/api/v1/team/roles", {
          method: "POST",
          body: JSON.stringify({ name: name.trim(), permissions: selected }),
        });
        setSuccess(fill(tm.roleCreated, { name: data.name }));
      }
      setName(""); setSelected([]);
      onDone();
    } catch (e) {
      setError(errText(e, tm.errFallback));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="role-name" className="text-[11px] font-medium text-[var(--ui-ink-2)]">
            {isSystem ? fill(tm.roleNameBuiltIn, { name: editing?.name ?? "" }) : editing ? fill(tm.roleNameEditing, { name: editing.name }) : tm.roleName}
          </label>
          <input
            id="role-name"
            value={name}
            readOnly={isSystem}
            aria-readonly={isSystem}
            onChange={(e) => { setName(e.target.value); setError(""); setSuccess(""); }}
            placeholder={tm.roleExample}
            className={`mt-1 ${FIELD} ${isSystem ? "cursor-not-allowed opacity-60" : ""}`}
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium text-[var(--ui-ink-2)]">
            {selected.length === 1 ? tm.selOne : fill(tm.selN, { n: fmt(selected.length) })}
          </span>
          <button type="button" onClick={handleSave} disabled={!canSave} className={BTN_PRIMARY}>
            {busy ? tm.saving : editing ? tm.saveChanges : selected.length ? fill(tm.createWith, { n: fmt(selected.length) }) : tm.createBtn}
          </button>
          {editing && (
            <button type="button" onClick={onDone} className={BTN_GHOST}>{tm.cancelBtn}</button>
          )}
        </div>
      </div>
      {success && <p className="text-[12px] font-medium text-[var(--ui-ink-2)]">{success}</p>}
      {error && <p className="text-[12px] font-semibold text-[var(--ui-ink)]">{error}</p>}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={tm.searchPh}
        aria-label={tm.searchAria}
        className={FIELD}
      />

      {areas.length === 0 ? (
        <p className="text-[12px] text-[var(--ui-ink-2)]">{tm.noCatalog}</p>
      ) : visibleAreas.length === 0 ? (
        <p className="text-[12px] text-[var(--ui-ink-2)]">{tm.noMatch}</p>
      ) : (
        <div className="grid gap-1.5 lg:grid-cols-2">
          {visibleAreas.map((area) => {
            const count = area.actions.filter((a) => selectedSet.has(a.permission)).length;
            const all = count === area.actions.length && count > 0;
            const open = q ? true : !!openAreas[area.area];
            return (
              <div key={area.area} className="overflow-hidden rounded-[8px] border border-[var(--ui-line)]">
                <div className="flex items-center gap-2 bg-[var(--ui-surface)] px-3 py-2">
                  <input
                    type="checkbox"
                    checked={all}
                    ref={(el) => { if (el) el.indeterminate = count > 0 && !all; }}
                    onChange={() => setArea(area, !all)}
                    aria-label={fill(tm.selectAllIn, { area: area.label })}
                    className="h-3.5 w-3.5 shrink-0 accent-[var(--ui-ink)]"
                  />
                  <button
                    type="button"
                    onClick={() => { if (!q) setOpenAreas((prev) => ({ ...prev, [area.area]: !prev[area.area] })); }}
                    aria-expanded={open}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <svg
                      viewBox="0 0 12 12"
                      fill="none"
                      className={`h-3 w-3 shrink-0 text-[var(--ui-ink-2)] transition-transform ${open ? "rotate-90" : ""}`}
                      aria-hidden
                    >
                      <path d="M4.5 2.5 8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    <span className="truncate text-[12px] font-semibold text-[var(--ui-ink)]">{area.label}</span>
                    {count > 0 && (
                      <span className="ui-chip shrink-0 px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)]">{fmt(count)}</span>
                    )}
                    <span className="ml-auto text-[12px] tabular-nums text-[var(--ui-ink-2)]">{fmt(count)}/{fmt(area.actions.length)}</span>
                  </button>
                </div>
                {open && (
                  <div className="p-4">
                    <div className="grid gap-0.5 sm:grid-cols-2">
                      {area.actions.map((act) => {
                        const on = selectedSet.has(act.permission);
                        return (
                          <label
                            key={act.permission}
                            className="flex cursor-pointer items-center gap-2 rounded-[8px] px-3 py-2 transition hover:bg-[var(--ui-sunken)]"
                          >
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => toggle(act.permission)}
                              className="h-3.5 w-3.5 shrink-0 accent-[var(--ui-ink)]"
                            />
                            <span className="text-[12px] font-medium text-[var(--ui-ink)]">{act.label}</span>
                            <span className="ml-auto font-mono text-[12px] text-[var(--ui-ink-2)]">{act.permission}</span>
                          </label>
                        );
                      })}
                    </div>
                    {!q && (
                      <div className="flex justify-end gap-3 px-2 pb-1 pt-1.5">
                        <button type="button" onClick={() => setArea(area, true)} className="text-[12px] font-semibold text-[var(--ui-ink)] hover:underline">
                          {tm.selectAll}
                        </button>
                        <button type="button" onClick={() => setArea(area, false)} className="text-[12px] font-semibold text-[var(--ui-ink-2)] hover:underline">
                          {tm.clear}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  const [members, setMembers] = useState<TeamMemberRow[]>([]);
  const [roles, setRoles] = useState<TeamRoleOption[]>([]);
  const [catalog, setCatalog] = useState<CatalogArea[]>([]);
  const [channels, setChannels] = useState<TeamChannelOption[]>([]);
  const [context, setContext] = useState<TeamContextInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [openAccess, setOpenAccess] = useState<string | null>(null);
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { t, locale } = useI18n();
  const tm = t.team;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);

  const loadMembers = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/team/members");
      setError(null);
      setMembers(data.members || []);
    } catch {
      setMembers([]);
      setError(tm.teamLoadFail);
    }
  }, [tm]);

  const loadRoles = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/team/roles");
      setRoles(data.roles || []);
    } catch {
      setRoles([]);
      setError(tm.rolesLoadFail);
    }
  }, [tm]);

  useEffect(() => {
    (async () => {
      try {
        setContext(await apiFetch("/api/v1/team/context"));
      } catch {
        /* not authenticated — nav gating handles the redirect */
      }
      try {
        const data = await apiFetch("/api/v1/team/channels");
        setChannels(data.channels || []);
      } catch {
        setChannels([]);
      }
      try {
        const data = await apiFetch("/api/v1/team/permissions");
        setCatalog(data.areas || []);
      } catch {
        setCatalog([]);
      }
      await Promise.all([loadMembers(), loadRoles()]);
      setLoading(false);
    })();
  }, [loadMembers, loadRoles]);

  // The owner is the backstop: their row is implicit and never gated by a role,
  // so trimming every checkbox on Admin can never lock them out.
  const canManage = !!context && (context.is_owner || !!context.permissions?.includes("team.manage"));
  const selfId = context?.member_id ?? null;
  const editingRole = roles.find((r) => r.id === editingRoleId) ?? null;

  const membersCount = useCallback(
    (roleId: string) => members.filter((m) => m.role_id === roleId).length,
    [members],
  );

  const mark = (key: string, on: boolean) =>
    setPending((prev) => {
      const next = { ...prev };
      if (on) next[key] = true;
      else delete next[key];
      return next;
    });

  const run = async (key: string, fn: () => Promise<void>) => {
    mark(key, true);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setNotice({ kind: "err", text: errText(e, tm.errFallback) });
    } finally {
      mark(key, false);
    }
  };

  const changeRole = (m: TeamMemberRow, roleId: string) =>
    run(`role:${m.id}`, async () => {
      await apiFetch(`/api/v1/team/members/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({ role_id: roleId }),
      });
      await loadMembers();
      const name = roles.find((r) => r.id === roleId)?.name || tm.roleCurrent;
      setNotice({ kind: "ok", text: fill(tm.nowRole, { email: m.email, name }) });
    });

  const saveChannels = (m: TeamMemberRow, levels: Record<string, Level>) =>
    run(`chan:${m.id}`, async () => {
      // Send every stored level verbatim, "none" included — it is a real
      // denial. Only channels left on "follow role" are absent, and the API
      // deletes the override row for those so the role decides again.
      await apiFetch(`/api/v1/team/members/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({ channel_levels: levels }),
      });
      await loadMembers();
      setOpenAccess(null);
      setNotice({ kind: "ok", text: fill(tm.chanUpdated, { email: m.email }) });
    });

  const toggleStatus = (m: TeamMemberRow) =>
    run(`status:${m.id}`, async () => {
      const next = m.status === "suspended" ? "active" : "suspended";
      await apiFetch(`/api/v1/team/members/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: next }),
      });
      await loadMembers();
      setNotice({
        kind: "ok",
        text: next === "suspended" ? fill(tm.suspendedMsg, { email: m.email }) : fill(tm.reactivated, { email: m.email }),
      });
    });

  const removeMember = (m: TeamMemberRow) =>
    run(`remove:${m.id}`, async () => {
      if (m.status === "invited") {
        await apiFetch(`/api/v1/team/invites/${m.id}`, { method: "DELETE" });
        await loadMembers();
        setNotice({ kind: "ok", text: fill(tm.inviteRevoked, { email: m.email }) });
        return;
      }
      await apiFetch(`/api/v1/team/members/${m.id}`, { method: "DELETE" });
      await loadMembers();
      setNotice({ kind: "ok", text: fill(tm.removedMember, { email: m.email }) });
    });

  const resendInvite = (m: TeamMemberRow) =>
    run(`resend:${m.id}`, async () => {
      await apiFetch(`/api/v1/team/invites/${m.id}/resend`, { method: "POST" });
      await loadMembers();
      setNotice({ kind: "ok", text: fill(tm.inviteResent, { email: m.email }) });
    });

  const deleteRole = (r: TeamRoleOption) =>
    run(`deleterole:${r.id}`, async () => {
      await apiFetch(`/api/v1/team/roles/${r.id}`, { method: "DELETE" });
      if (editingRoleId === r.id) setEditingRoleId(null);
      await loadRoles();
      setNotice({ kind: "ok", text: fill(tm.roleDeleted, { name: r.name }) });
    });

  const inviteableRoles = roles;

  return (
    <div className="team-ui relative h-full space-y-8 overflow-y-auto p-4 pb-24 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)]">{tm.title}</h1>
          <p className="mt-0.5 text-[13px] text-[var(--ui-ink-2)]">
            {tm.sub}
          </p>
        </div>
        {context && (
          <p className="text-[12px] text-[var(--ui-ink-2)]">
            {context.business_name || tm.workspaceFallback} · <span className="font-semibold text-[var(--ui-ink)]">{context.role_name || tm.roleFallback}</span>
            {!canManage && <span className="ml-2 text-[var(--ui-ink-2)]">{tm.readOnly}</span>}
          </p>
        )}
      </div>

      {loading ? (
        <p className="text-[13px] text-[var(--ui-ink-2)]">{tm.loading}</p>
      ) : (
        <div className="space-y-10">
          {notice && (
            <p
              role="status"
              aria-live="polite"
              // Three colours only, so an error is a heavier border and bolder
              // text rather than a red tint.
              className={`rounded-[8px] border px-4 py-3 text-[12px] ${
                notice.kind === "ok"
                  ? "border-[var(--ui-line-strong)] bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
                  : "border-[var(--ui-ink)] bg-[var(--ui-sunken)] font-bold text-[var(--ui-ink)]"
              }`}
            >
              {notice.text}
            </p>
          )}

          {/* Members */}
          <section className={`ui-panel bg-[var(--ui-surface)] p-8`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-[15px] font-semibold text-[var(--ui-ink)]">{tm.membersTitle}</h2>
              <div className="flex items-center gap-2">
                <span className="ui-chip shrink-0 px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)]">
                  {fmt(members.length)}
                </span>
                {members.some((m) => m.status === "invited") && (
                  <span className="text-[11px] text-[var(--ui-ink-2)]">
                    {fill(tm.awaiting, { n: fmt(members.filter((m) => m.status === "invited").length) })}
                  </span>
                )}
              </div>
            </div>
            <div className="mt-4">
              {members.length === 0 ? (
                error ? (
                  // A failed load must not look like an empty team: say what
                  // happened and offer the one action that fixes it.
                  <div className="col-span-full rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4" role="alert">
                    <p className="text-[13px] font-bold text-[var(--ui-ink)]">{error}</p>
                    <button
                      type="button"
                      onClick={() => void Promise.all([loadMembers(), loadRoles()])}
                      className={`${BTN} mt-3`}
                    >
                      {tm.tryAgain}
                    </button>
                  </div>
                ) : (
                  <p className="col-span-full text-[13px] text-[var(--ui-ink-2)]">{tm.noMembers}</p>
                )
              ) : (
                members.map((m) => {
                  const isOwner = !!m.is_owner;
                  const isSelf = !!m.id && m.id === selfId;
                  const editable = canManage && !isOwner && !isSelf && !!m.id;
                  const why = isOwner
                    ? tm.whyOwner
                    : isSelf
                      ? tm.whySelf
                      : !canManage
                        ? tm.whyNoPerm
                        : undefined;
                  const key = m.id || m.email;
                  const overrideCount = Object.keys(m.channels || {}).length;
                  // Mirrors the backend fallback: an override wins, else the
                  // role's channels.edit / channels.view default decides.
                  const memberRole = roles.find((r) => r.id === m.role_id);
                  const rolePerms = new Set(memberRole?.permissions || []);
                  const roleDefault: Level = rolePerms.has("channels.edit")
                    ? "edit"
                    : rolePerms.has("channels.view")
                      ? "view"
                      : "none";
                  return (
                    <div key={key} className="border-b border-[var(--ui-line)] last:border-0">
                      <div
                        className="grid items-center gap-3 py-4 lg:grid-cols-[minmax(0,1fr)_280px_auto]"
                      >
                      <div className="flex min-w-0 items-center gap-3">
                        <Initial label={m.name || m.email} owner={isOwner} avatarUrl={m.avatar_url} />
                        <div className="min-w-0">
                          <p className="truncate text-[13px] font-semibold text-[var(--ui-ink)]">{m.email}</p>
                          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] text-[var(--ui-ink-2)]">
                            <StatusBadge status={m.status} />
                            {m.status === "invited" && m.invited_at && <span>{fill(tm.sent, { date: shortDate(m.invited_at, dateLocale) })}</span>}
                            {m.status === "active" && m.accepted_at && <span>{fill(tm.joined, { date: shortDate(m.accepted_at, dateLocale) })}</span>}
                            {isSelf && <span>{tm.you}</span>}
                          </p>
                        </div>
                      </div>

                      <div className="min-w-0">
                        {editable ? (
                          <RoleSelect
                            value={m.role_id || ""}
                            roles={roles}
                            catalog={catalog}
                            membersCount={membersCount}
                            onChange={(id) => void changeRole(m, id)}
                            pending={pending[`role:${m.id}`]}
                            label={fill(tm.roleFor, { email: m.email })}
                            summary={false}
                            className={`${FIELD} min-w-0 px-3 py-2.5 text-[12px]`}
                          />
                        ) : (
                          <div className="min-w-0">
                            <RoleBadge name={m.role_name} isOwner={isOwner} />
                            {why && <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">{why}</p>}
                          </div>
                        )}
                      </div>

                      {editable ? (
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          {pending[`role:${m.id}`] && <Spinner label={tm.savingRole} />}
                          <button
                            type="button"
                            onClick={() => setOpenAccess(openAccess === key ? null : key)}
                            aria-expanded={openAccess === key}
                            className={`${BTN_GHOST} px-4 py-2.5 text-[12px] whitespace-nowrap`}
                          >
                            {overrideCount > 0 ? (overrideCount === 1 ? fill(tm.ovrOne, { n: fmt(overrideCount) }) : fill(tm.ovrN, { n: fmt(overrideCount) })) : tm.followsRole}
                          </button>
                          {m.status === "invited" && (
                            <button type="button" onClick={() => void resendInvite(m)} disabled={pending[`resend:${m.id}`]} className={`${BTN_GHOST} px-4 py-2.5 text-[12px] whitespace-nowrap`}>
                              {pending[`resend:${m.id}`] ? tm.sending : tm.resend}
                            </button>
                          )}
                          {m.status !== "invited" && (
                            <button type="button" onClick={() => void toggleStatus(m)} disabled={pending[`status:${m.id}`]} className={`${BTN_GHOST} px-4 py-2.5 text-[12px] whitespace-nowrap`}>
                              {pending[`status:${m.id}`] ? tm.working : m.status === "suspended" ? tm.reactivate : tm.suspend}
                            </button>
                          )}
                          <ConfirmButton
                            label={m.status === "invited" ? tm.removeInvite : tm.removeBtn}
                            confirmLabel={m.status === "invited" ? tm.confirmRevoke : tm.confirmRemove}
                            pending={pending[`remove:${m.id}`]}
                            onConfirm={() => void removeMember(m)}
                            className={`${BTN_DANGER} px-4 py-2.5`}
                          />
                        </div>
                      ) : null}

                      </div>

                      {editable && openAccess === key && (
                        <div className="pb-5">
                        <ChannelAccess
                          key={key}
                          channels={channels}
                          value={m.channels || {}}
                          roleLabel={memberRole?.name || m.role_name || tm.roleCurrent}
                          roleDefault={roleDefault}
                          pending={pending[`chan:${m.id}`]}
                          onSave={(levels) => void saveChannels(m, levels)}
                        />
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Invite member */}
          <section className={`ui-panel bg-[var(--ui-surface)] p-8`}>
            <h2 className="text-[15px] font-semibold text-[var(--ui-ink)]">{tm.inviteTitle}</h2>
            <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
              {tm.inviteSub}
            </p>
            {inviteableRoles.length === 0 ? (
              <p className="mt-3 text-[12px] text-[var(--ui-ink-2)]">{tm.noRolesYet}</p>
            ) : (
              <InviteForm
                roles={inviteableRoles}
                catalog={catalog}
                members={members}
                channels={channels}
                membersCount={membersCount}
                onInvited={loadMembers}
              />
            )}
          </section>

          {/* Roles */}
          <section className={`ui-panel bg-[var(--ui-surface)] p-8`}>
            <h2 className="text-[15px] font-semibold text-[var(--ui-ink)]">{tm.rolesTitle}</h2>
            <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
              {tm.rolesSub}
            </p>
            {roles.length === 0 ? (
              error ? (
                <p className="mt-4 text-[13px] font-bold text-[var(--ui-ink)]" role="alert">
                  {error}
                </p>
              ) : (
                <p className="mt-4 text-[13px] text-[var(--ui-ink-2)]">{tm.rolesEmpty}</p>
              )
            ) : (
              <PermissionMatrix
                roles={roles}
                catalog={catalog}
                membersCount={membersCount}
                canManage={canManage}
                onEdit={(r) => { setEditingRoleId(r.id); setNotice(null); }}
                onDelete={(r) => void deleteRole(r)}
                pending={pending}
              />
            )}
          </section>

          {/* Role builder */}
          <section className={`ui-panel bg-[var(--ui-surface)] p-8`}>
            <h2 className="text-[15px] font-semibold text-[var(--ui-ink)]">
              {editingRole ? fill(tm.builderEditing, { name: editingRole.name }) : tm.builderTitle}
            </h2>
            <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
              {editingRole
                ? editingRole.is_system
                  ? fill(tm.builderSubSystem, { name: editingRole.name })
                  : tm.builderSubEdit
                : tm.builderSubNew}
            </p>
            {canManage ? (
              <RoleBuilder
                key={editingRole?.id ?? "new"}
                editing={editingRole}
                catalog={catalog}
                onDone={() => { setEditingRoleId(null); void loadRoles(); }}
              />
            ) : (
              <p className="mt-3 text-[12px] text-[var(--ui-ink-2)]">{tm.cannotManage}</p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
