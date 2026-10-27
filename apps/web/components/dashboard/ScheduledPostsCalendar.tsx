"use client";

import { useMemo, useState } from "react";
import Image from "next/image";

export interface ScheduledEntry {
  id: string;
  name: string;
  scheduledAt: string;
  endAt?: string;
  platform?: string;
  thumbnailUrl?: string;
  color?: string;
  description?: string;
  status?: string;
}

interface Props {
  items: ScheduledEntry[];
  title?: string;
  /** Called with an ISO date string when the user clicks "Schedule a publish" on a day. */
  onScheduleDate?: (dateIso: string) => void;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const PLATFORM_COLORS: Record<string, string> = {
  "Google Business Profile": "#4285F4",
  "Instagram": "#E4405F",
  "Facebook": "#1877F2",
  "WhatsApp": "#25D366",
  "Twitter": "#1DA1F2",
  "LinkedIn": "#0A66C2",
};

function platformColor(platform?: string, override?: string): string {
  if (override) return override;
  if (platform && PLATFORM_COLORS[platform]) return PLATFORM_COLORS[platform];
  return "#3D1D6E";
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function toIsoDate(year: number, month: number, day: number): string {
  const m = String(month + 1).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return `${year}-${m}-${d}`;
}

export default function ScheduledPostsCalendar({ items, onScheduleDate }: Props) {
  const scheduled = useMemo(() => items.filter((m) => !!m.scheduledAt), [items]);

  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(() => new Date());
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);

  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  const firstOfMonth = new Date(year, month, 1);
  const startWeekday = firstOfMonth.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const byDate = useMemo(() => {
    const map = new Map<string, ScheduledEntry[]>();
    scheduled.forEach((m) => {
      if (!m.scheduledAt) return;
      const d = new Date(m.scheduledAt);
      const key = dayKey(d);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(m);
    });
    return map;
  }, [scheduled]);

  const nextUpcoming = useMemo(() => {
    const now = Date.now();
    return [...scheduled]
      .filter((m) => m.scheduledAt && new Date(m.scheduledAt).getTime() > now)
      .sort((a, b) => new Date(a.scheduledAt).getTime() - new Date(b.scheduledAt).getTime())[0];
  }, [scheduled]);

  const handleDayClick = (day: number, e: React.MouseEvent) => {
    const dateObj = new Date(year, month, day);
    if (dateObj < todayStart) return; // no past dates
    const key = `${year}-${month}-${day}`;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setAnchor({ x: rect.left + rect.width / 2, y: rect.bottom });
    setSelectedDay(day);
  };

  const selectedItems = selectedDay !== null ? byDate.get(`${year}-${month}-${selectedDay}`) ?? [] : [];
  const selectedDateIso = selectedDay !== null ? toIsoDate(year, month, selectedDay) : "";
  const isSelectedPast = selectedDay !== null && new Date(year, month, selectedDay) < todayStart;

  return (
    <div className="rounded-xl border border-ink/[0.1] dark:border-fog/[0.1] bg-white dark:bg-ink overflow-hidden shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-ink/[0.04] dark:hover:bg-fog/[0.04]"
        aria-expanded={open}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-deep-violet/10 text-deep-violet">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <path d="M16 2v4M8 2v4M3 10h18" strokeLinecap="round" />
            </svg>
          </span>
          <div className="min-w-0">
            <p className="text-[14px] font-semibold text-ink dark:text-fog">
              {scheduled.length} scheduled post{scheduled.length === 1 ? "" : "s"}
            </p>
            {nextUpcoming ? (
              <p className="truncate text-[12px] text-ink/50 dark:text-fog/50">
                Next: {new Date(nextUpcoming.scheduledAt).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} — {nextUpcoming.name}
              </p>
            ) : (
              <p className="text-[12px] text-ink/40 dark:text-fog/40">Nothing queued — schedule a photo to get started.</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {scheduled.length > 0 && (
            <span className="rounded-full bg-deep-violet/10 px-2.5 py-0.5 text-[11px] font-semibold text-deep-violet">
              {scheduled.length}
            </span>
          )}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`shrink-0 text-ink/40 dark:text-fog/40 transition-transform duration-200 ${open ? "rotate-180" : ""}`} aria-hidden>
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </button>

      {open && (
        <div className="border-t border-ink/[0.06] dark:border-fog/[0.06] p-4">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => setCursor(new Date(year, month - 1, 1))} className="rounded-lg p-1.5 text-ink/50 dark:text-fog/50 hover:bg-ink/[0.06] dark:hover:bg-fog/[0.06] transition" aria-label="Previous month">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
              <button type="button" onClick={() => setCursor(new Date(year, month + 1, 1))} className="rounded-lg p-1.5 text-ink/50 dark:text-fog/50 hover:bg-ink/[0.06] dark:hover:bg-fog/[0.06] transition" aria-label="Next month">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            </div>
            <p className="text-[15px] font-semibold text-ink dark:text-fog">{MONTHS[month]} {year}</p>
            <button type="button" onClick={() => setCursor(new Date())} className="rounded-lg border border-ink/[0.1] dark:border-fog/[0.1] px-3 py-1 text-[12px] font-medium text-ink/60 dark:text-fog/60 hover:bg-ink/[0.04] dark:hover:bg-fog/[0.04] transition">Today</button>
          </div>

          <div className="grid grid-cols-7 gap-px mb-1">
            {WEEKDAYS.map((w) => (
              <div key={w} className="py-1 text-center text-[10px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">{w}</div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-px">
            {cells.map((day, i) => {
              if (day === null) return <div key={`empty-${i}`} className="h-16 sm:h-20" />;
              const key = `${year}-${month}-${day}`;
              const list = byDate.get(key);
              const has = !!list && list.length > 0;
              const todayFlag = sameDay(new Date(year, month, day), today);
              const isPast = new Date(year, month, day) < todayStart;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={(e) => !isPast && handleDayClick(day, e)}
                  disabled={isPast}
                  className={`relative flex flex-col items-start p-1.5 sm:p-2 h-16 sm:h-20 rounded-md text-left transition ${
                    isPast
                      ? "text-ink/30 dark:text-fog/30 cursor-not-allowed"
                      : has
                        ? "bg-deep-violet/5 hover:bg-deep-violet/10 cursor-pointer"
                        : "text-ink/70 dark:text-fog/70 hover:bg-ink/[0.04] dark:hover:bg-fog/[0.04] cursor-pointer"
                  } ${todayFlag ? "ring-2 ring-deep-violet ring-inset" : ""}`}
                >
                  <span className={`text-[12px] font-medium ${todayFlag ? "text-deep-violet font-bold" : isPast ? "text-ink/30 dark:text-fog/30" : "text-ink/70 dark:text-fog/70"}`}>
                    {day}
                  </span>
                  {has && !isPast && (
                    <div className="mt-1 flex flex-col gap-0.5 w-full overflow-hidden">
                      {list!.slice(0, 2).map((item) => (
                        <div key={item.id} className="flex items-center gap-1 rounded px-1 py-0.5 text-[9px] font-medium text-white truncate" style={{ backgroundColor: platformColor(item.platform, item.color) }}>
                          <span className="truncate">{item.name}</span>
                        </div>
                      ))}
                      {list!.length > 2 && (
                        <span className="text-[9px] text-ink/40 dark:text-fog/40 font-medium">+{list!.length - 2} more</span>
                      )}
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {scheduled.length === 0 && (
            <p className="mt-4 text-center text-[13px] text-ink/40 dark:text-fog/40">No scheduled posts yet. Schedule a photo to see it here.</p>
          )}

          {scheduled.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-3 border-t border-ink/[0.06] dark:border-fog/[0.06] pt-3">
              {Object.entries(PLATFORM_COLORS).filter(([p]) => scheduled.some(s => s.platform === p)).map(([platform, color]) => (
                <div key={platform} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
                  <span className="text-[11px] text-ink/50 dark:text-fog/50">{platform}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* popover for any date */}
      {selectedDay !== null && anchor && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => { setSelectedDay(null); setAnchor(null); }} />
          <div
            className="fixed z-50 w-72 rounded-xl border border-ink/[0.1] dark:border-fog/[0.1] bg-white p-4 shadow-xl"
            style={{ left: Math.min(anchor.x - 144, window.innerWidth - 300), top: anchor.y + 8 }}
          >
            <p className="text-[10px] font-bold uppercase tracking-widest text-ink/40 dark:text-fog/40 mb-2">
              {MONTHS[month]} {selectedDay}, {year}
            </p>
            {selectedItems.length > 0 && (
              <div className="space-y-3 mb-3">
                {selectedItems.map((item) => (
                  <div key={item.id} className="flex gap-3">
                    {item.thumbnailUrl && (
                      <Image src={item.thumbnailUrl} alt="" width={48} height={48} className="h-12 w-12 rounded-lg object-cover shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-semibold text-ink dark:text-fog truncate">{item.name}</p>
                      <p className="text-[11px] text-ink/50 dark:text-fog/50">
                        {new Date(item.scheduledAt).toLocaleString(undefined, { hour: "numeric", minute: "2-digit" })}
                        {item.endAt ? ` – ${new Date(item.endAt).toLocaleString(undefined, { hour: "numeric", minute: "2-digit" })}` : ""}
                      </p>
                      <div className="mt-1 flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: platformColor(item.platform, item.color) }} />
                        <span className="text-[10px] text-ink/40 dark:text-fog/40">{item.platform ?? "Scheduled"}</span>
                        {item.status && <span className="text-[10px] text-ink/40 dark:text-fog/40">· {item.status}</span>}
                      </div>
                      {item.description && <p className="mt-1 text-[11px] text-ink/50 dark:text-fog/50 line-clamp-2">{item.description}</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {selectedItems.length === 0 && (
              <p className="text-[12px] text-ink/40 dark:text-fog/40 mb-3">No posts scheduled for this day.</p>
            )}
            {onScheduleDate && (
              <button
                type="button"
                onClick={() => {
                  onScheduleDate(selectedDateIso);
                  setSelectedDay(null);
                  setAnchor(null);
                }}
                className="w-full rounded-lg bg-deep-violet py-2 text-[12px] font-semibold text-white hover:bg-deep-violet/90 transition"
              >
                Schedule a publish
              </button>
            )}
            <button
              type="button"
              onClick={() => { setSelectedDay(null); setAnchor(null); }}
              className="mt-2 w-full rounded-lg border border-ink/[0.1] dark:border-fog/[0.1] bg-ink/[0.04] dark:bg-fog/[0.04] py-1.5 text-[11px] font-semibold text-ink/60 dark:text-fog/60 hover:bg-ink/[0.06] dark:hover:bg-fog/[0.06] transition"
            >
              Close
            </button>
          </div>
        </>
      )}
    </div>
  );
}