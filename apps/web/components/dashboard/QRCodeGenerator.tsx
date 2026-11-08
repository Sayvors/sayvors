"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { QRCodeSVG } from "qrcode.react";
import { useI18n } from "@/lib/i18n/I18nProvider";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

interface BusinessProfile {
  listing_id: string;
  listing_name: string;
  listing_google_id?: string | null;
  address?: string | null;
  phone_number?: string | null;
  website_url?: string | null;
  maps_url?: string | null;
  total_reviews?: number;
  average_rating?: number;
}

export default function QRCodeGenerator() {
  const { t, locale } = useI18n();
  const r = t.reviews.qr;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const fmtRating = (n: number) =>
    n.toLocaleString(locale === "ar" ? "ar-SA" : "en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const [profiles, setProfiles] = useState<BusinessProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const qrRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels?limit=100");
        if (cancelled) return;
        const list = ((data.channels ?? []) as {
          id: string;
          platform: string;
          status: string;
          display_name: string | null;
          listing_id?: string | null;
          place_id?: string | null;
          maps_url?: string | null;
        }[])
          .filter(
            (c) =>
              c.platform === "google_reviews" &&
              c.status === "active" &&
              (c.place_id || c.maps_url)
          )
          .map((c) => ({
            listing_id: c.listing_id ?? c.id,
            listing_name: c.display_name ?? r.locationFallback,
            listing_google_id: c.place_id ?? null,
            maps_url: c.maps_url ?? null,
          }));
        setProfiles(list);
        if (list.length > 0) {
          setSelectedId(list[0].listing_id);
        }
      } catch {
        if (!cancelled) setError(r.loadFailed);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = profiles.find((p) => p.listing_id === selectedId);

  const getReviewUrl = (profile: BusinessProfile): string => {
    if (profile.listing_google_id) {
      // The place_id link opens Google's rate-and-review composer directly.
      // The maps/profile URLs land the customer on the listing, where they'd
      // have to find and tap "Write a review" themselves.
      return `https://search.google.com/local/writereview?placeid=${profile.listing_google_id}`;
    }
    if (profile.maps_url) return profile.maps_url;
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(profile.listing_name)}`;
  };

  const handleDownload = async () => {
    if (!qrRef.current || !selected) return;
    setDownloading(true);
    try {
      const svg = qrRef.current.querySelector("svg");
      if (!svg) return;
      const svgData = new XMLSerializer().serializeToString(svg);
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const img = new Image();
      img.onload = () => {
        canvas.width = 1024;
        canvas.height = 1024;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, 1024, 1024);
        ctx.drawImage(img, 0, 0, 1024, 1024);
        const link = document.createElement("a");
        link.download = `${selected.listing_name.replace(/[^a-z0-9]/gi, "-").toLowerCase()}-review-qr.png`;
        link.href = canvas.toDataURL("image/png");
        link.click();
        setDownloading(false);
      };
      img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svgData)));
    } catch {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <section aria-label={r.sectionAria} className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <div className="h-3 w-32 animate-pulse rounded bg-ink/[0.07]" />
        <div className="mt-3 h-64 animate-pulse rounded-xl bg-ink/[0.05]" />
      </section>
    );
  }

  if (error) {
    return (
      <section aria-label={r.sectionAria} className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <p className="text-[12px] font-medium text-coral">{error}</p>
      </section>
    );
  }

  if (profiles.length === 0) {
    return (
      <section aria-label={r.sectionAria} className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <path d="M14 14h3v3h-3zM21 14v.01M14 21v.01M21 21v.01M18 18h.01" />
            </svg>
          </span>
          <div>
            <h2 className="text-[14px] font-bold text-ink">{r.title}</h2>
            <p className="text-[11px] text-ink/45">{r.sub}</p>
          </div>
        </div>
        <p className="mt-4 text-[12px] text-ink/50">{r.empty}</p>
      </section>
    );
  }

  return (
    <section aria-label={r.sectionAria} className="rounded-2xl border-2 border-white bg-white/80 p-4 backdrop-blur-sm sm:p-5">
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
            <path d="M14 14h3v3h-3zM21 14v.01M14 21v.01M21 21v.01M18 18h.01" />
          </svg>
        </span>
        <div>
          <h2 className="text-[14px] font-bold text-ink">Review QR Code</h2>
          <p className="text-[11px] text-ink/45">Generate a QR code for Google reviews</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-[1fr_auto]">
        <div className="order-2 space-y-3 sm:order-1">
          <div>
            <label htmlFor="qr-business-select" className="mb-1 block text-[11px] font-semibold text-ink/55">
              {r.businessLabel}
            </label>
            <select
              id="qr-business-select"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              className="input-field w-full"
            >
              {profiles.map((p) => (
                <option key={p.listing_id} value={p.listing_id}>
                  {p.listing_name}
                </option>
              ))}
            </select>
          </div>

          {selected && (
            <div className="min-w-0 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-deep-violet/10 text-deep-violet">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                    <circle cx="12" cy="10" r="3" />
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-[12px] font-bold leading-snug text-ink">{selected.listing_name}</p>
                  {selected.address && (
                    <p className="mt-0.5 break-words text-[10px] leading-snug text-ink/45">{selected.address}</p>
                  )}
                </div>
              </div>
              {selected.total_reviews != null && (
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink/45">
                  <span className="inline-flex items-center gap-1">
                    <span className="font-bold text-amber-600">{"★".repeat(Math.max(0, Math.min(5, Math.round(selected.average_rating ?? 0))))}</span>
                    {selected.average_rating != null ? fmtRating(selected.average_rating) : "—"}
                  </span>
                  <span>{selected.total_reviews != null ? fill(r.reviewsLine, { n: fmt(selected.total_reviews) }) : ""}</span>
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleDownload}
            disabled={!selected || downloading}
            className="w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.99] disabled:opacity-50"
          >
            {downloading ? r.generating : r.download}
          </button>
        </div>

        {selected && (
          <div className="order-1 flex flex-col items-center gap-2 sm:order-2">
            <div
              ref={qrRef}
              className="w-fit rounded-2xl border-2 border-ink/[0.06] bg-white p-3 shadow-sm sm:p-4"
            >
              <QRCodeSVG
                value={getReviewUrl(selected)}
                size={180}
                bgColor="#ffffff"
                fgColor="#1a1230"
                level="H"
                className="h-auto w-36 sm:w-[180px]"
                imageSettings={{
                  src: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjNWIyZDhlIiBzdHJva2Utd2lkdGg9IjEuOCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNMjEgMTBjMCA3LTkgMTMtOSAxM3MtOS02LTktMTNhOSA5IDAgMDExOCAweiIvPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTAiIHI9IjMiLz48L3N2Zz4=",
                  height: 36,
                  width: 36,
                  excavate: true,
                }}
              />
            </div>
            <p className="text-center text-[10px] font-medium text-ink/40">
              {r.scanHint}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
