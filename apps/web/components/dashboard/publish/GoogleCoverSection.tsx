"use client";

/** Separate Google Cover section: the real image Google reports, its status,
 *  and a Replace action that re-opens the composer with the Promotion format
 *  pre-selected for the same Google Business Profile.
 *
 *  A changed status is a warning, not a silent state: Google can swap the
 *  cover without asking, and the merchant needs to see it and replace again.
 */
import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api-rag";

const INK = "text-[#14101F] dark:text-white";
const INK2 = "text-[#3B2D5E] dark:text-white/70";

type Monitor = {
  id: string;
  channel_id: string;
  status: "ok" | "changed" | "error";
  image_url: string | null;
  expected_image_url: string | null;
  actual_image_url: string | null;
  message: string;
  drift_count: number;
  last_checked_at: string | null;
  auto_replace: boolean;
  auto_replace_count: number;
  max_auto_replaces: number;
};

const COPY = {
  en: {
    title: "Google cover photo",
    subtitle: "The image Google currently shows for your Business Profile.",
    empty: "No cover tracked yet. Publish a Promotion to set one.",
    ok: "Your cover is set",
    changedTitle: "Google changed your cover photo",
    changedBody: "Replace it again to put your image back.",
    errorTitle: "Could not check your cover",
    replace: "Replace",
    replaceAgain: "Replace again",
    dismiss: "Dismiss",
    never: "Not checked yet",
    checked: "Last checked",
    autoReplace: "Re-publish it automatically when Google changes it",
    autoLimit: "Stops after 3 tries, then asks you.",
  },

  ar: {
    title: "صورة غلاف جوجل",
    subtitle: "الصورة التي تعرضها جوجل حالياً لملف نشاطك التجاري.",
    empty: "لا توجد صورة غلاف بعد. انشر عرضاً ترويجياً لتعيينها.",
    ok: "صورة الغلاف مفعّلة",
    changedTitle: "غيّرت جوجل صورة الغلاف",
    changedBody: "استبدلها مرة أخرى لإرجاع صورتك.",
    errorTitle: "تعذّر التحقق من صورة الغلاف",
    replace: "استبدال",
    replaceAgain: "استبدال مرة أخرى",
    dismiss: "تجاهل",
    never: "لم يتم التحقق بعد",
    checked: "آخر تحقق",
    autoReplace: "أعد نشرها تلقائياً عندما تغيّرها جوجل",
    autoLimit: "يتوقف بعد 3 محاولات ثم يسألك.",
  },
};

export default function GoogleCoverSection({
  locale,
  onReplace,
}: {
  locale: string;
  onReplace: (channelId: string) => void;
}) {
  const t = locale.startsWith("ar") ? COPY.ar : COPY.en;
  const [rows, setRows] = useState<Monitor[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/media/cover-monitors");
      if (Array.isArray(data)) setRows(data as Monitor[]);
    } catch {
      // A failed poll keeps the last known state visible instead of blanking it.
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 60_000);
    return () => clearInterval(id);
  }, [load]);

  const setAuto = async (id: string, enabled: boolean) => {
    setBusy(true);
    try {
      await apiFetch(`/api/v1/media/cover-monitors/${encodeURIComponent(id)}/auto-replace`, {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async (id: string) => {
    setBusy(true);
    try {
      await apiFetch(`/api/v1/media/cover-monitors/${encodeURIComponent(id)}/acknowledge`, {
        method: "POST",
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="google-cover-h" className="clay-panel bg-[var(--ui-surface)] p-4 sm:p-5">
      <h2 id="google-cover-h" className={`text-[15px] font-bold ${INK}`}>
        {t.title}
      </h2>
      <p className={`mt-0.5 mb-3 text-[12px] ${INK2}`}>{t.subtitle}</p>

      {rows.length === 0 ? (
        <p className={`text-[12px] ${INK2}`}>{t.empty}</p>
      ) : (
        <div className="space-y-3">
          {rows.map((row) => {
            const changed = row.status === "changed";
            const errored = row.status === "error";
            const image = row.image_url;
            return (
              <article
                key={row.id}
                className="flex flex-col gap-3 rounded-[12px] border border-[#3D1D6E]/10 bg-white p-3 sm:flex-row sm:items-center"
              >
                <div className="h-[92px] w-full shrink-0 overflow-hidden rounded-[8px] bg-[#F4F2F7] sm:h-[72px] sm:w-[128px]">
                  {image ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={image}
                      alt={t.title}
                      className="h-full w-full object-cover"
                      referrerPolicy="no-referrer"
                    />
                  ) : null}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        changed || errored
                          ? "bg-[#FF4F6E]/12 text-[#B32442]"
                          : "bg-[#10b981]/12 text-[#0B6E52]"
                      }`}
                    >
                      {changed ? t.changedTitle : errored ? t.errorTitle : t.ok}
                    </span>
                    {row.last_checked_at ? (
                      <span className={`text-[10px] ${INK2}`}>
                        {t.checked}: {new Date(row.last_checked_at).toLocaleString()}
                      </span>
                    ) : (
                      <span className={`text-[10px] ${INK2}`}>{t.never}</span>
                    )}
                  </div>
                  {changed ? (
                    <p className="mt-1 text-[12px] font-semibold text-[#B32442]">{t.changedBody}</p>
                  ) : null}
                  {errored && row.message ? (
                    <p className="mt-1 text-[12px] text-[#B32442]">{row.message}</p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => onReplace(row.channel_id)}
                      className="rounded-[10px] bg-[#3D1D6E] px-3 py-1.5 text-[11px] font-bold text-white transition-transform active:translate-y-[2px] active:scale-[0.98]"
                    >
                      {changed ? t.replaceAgain : t.replace}
                    </button>
                    {changed ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void dismiss(row.id)}
                        className="rounded-[10px] border border-[#3D1D6E]/20 bg-white px-3 py-1.5 text-[11px] font-bold text-[#3D1D6E] disabled:opacity-50"
                      >
                        {t.dismiss}
                      </button>
                    ) : null}
                  </div>
                  <label className="mt-2 flex cursor-pointer items-start gap-2">
                    <input
                      type="checkbox"
                      checked={row.auto_replace}
                      disabled={busy}
                      onChange={(e) => void setAuto(row.id, e.target.checked)}
                      className="mt-0.5 h-3.5 w-3.5 accent-[#3D1D6E]"
                    />
                    <span className={`text-[10.5px] leading-snug ${INK2}`}>
                      {t.autoReplace}
                      <span className="block opacity-70">{t.autoLimit}</span>
                    </span>
                  </label>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
