"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { QRCodeSVG } from "qrcode.react";

interface BusinessProfile {
  listing_id: string;
  listing_name: string;
  address?: string | null;
  phone_number?: string | null;
  website_url?: string | null;
  maps_url?: string | null;
  total_reviews?: number;
  average_rating?: number;
}

export default function QRCodeGenerator() {
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
        const data = await apiFetch("/api/v1/integrations/localith/connections");
        if (cancelled) return;
        const list = Array.isArray(data) ? data : [];
        setProfiles(list);
        if (list.length > 0) {
          setSelectedId(list[0].listing_id);
        }
      } catch {
        if (!cancelled) setError("Could not load business profiles");
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
      <section aria-label="QR code generator" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <div className="h-3 w-32 animate-pulse rounded bg-ink/[0.07]" />
        <div className="mt-3 h-64 animate-pulse rounded-xl bg-ink/[0.05]" />
      </section>
    );
  }

  if (error) {
    return (
      <section aria-label="QR code generator" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <p className="text-[12px] font-medium text-coral">{error}</p>
      </section>
    );
  }

  if (profiles.length === 0) {
    return (
      <section aria-label="QR code generator" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
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
        <p className="mt-4 text-[12px] text-ink/50">No business profiles found. Connect a Google business to generate QR codes.</p>
      </section>
    );
  }

  return (
    <section aria-label="QR code generator" className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
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

      <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto]">
        <div className="space-y-3">
          <div>
            <label htmlFor="qr-business-select" className="mb-1 block text-[11px] font-semibold text-ink/55">
              Business Profile
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
            <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-deep-violet/10 text-deep-violet">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                    <circle cx="12" cy="10" r="3" />
                  </svg>
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[12px] font-bold text-ink">{selected.listing_name}</p>
                  {selected.address && (
                    <p className="truncate text-[10px] text-ink/45">{selected.address}</p>
                  )}
                </div>
              </div>
              {selected.total_reviews != null && (
                <div className="mt-2 flex items-center gap-3 text-[10px] text-ink/45">
                  <span className="inline-flex items-center gap-1">
                    <span className="font-bold text-amber-600">{"★".repeat(Math.max(0, Math.min(5, Math.round(selected.average_rating ?? 0))))}</span>
                    {selected.average_rating?.toFixed(1)}
                  </span>
                  <span>{selected.total_reviews} reviews</span>
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleDownload}
            disabled={!selected || downloading}
            className="w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.99] disabled:opacity-50"
          >
            {downloading ? "Generating..." : "Download QR Code"}
          </button>
        </div>

        {selected && (
          <div className="flex flex-col items-center gap-2">
            <div
              ref={qrRef}
              className="rounded-2xl border-2 border-ink/[0.06] bg-white p-4 shadow-sm"
            >
              <QRCodeSVG
                value={getReviewUrl(selected)}
                size={180}
                bgColor="#ffffff"
                fgColor="#1a1230"
                level="H"
                imageSettings={{
                  src: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjNWIyZDhlIiBzdHJva2Utd2lkdGg9IjEuOCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNMjEgMTBjMCA3LTkgMTMtOSAxM3MtOS02LTktMTNhOSA5IDAgMDExOCAweiIvPjxjaXJjbGUgY3g9IjEyIiBjeT0iMTAiIHI9IjMiLz48L3N2Zz4=",
                  height: 36,
                  width: 36,
                  excavate: true,
                }}
              />
            </div>
            <p className="text-center text-[10px] font-medium text-ink/40">
              Scan to leave a review
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
