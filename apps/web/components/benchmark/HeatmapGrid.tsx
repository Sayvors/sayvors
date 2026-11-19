"use client";

import { useEffect, useState } from "react";
import { getBenchmarkPlaceDetails, type PlaceDetails, type SavedPlace } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

/** Solid heat colour from rating: red < 3.8, amber < 4.4, green otherwise. */
function heatTone(rating: number | null): { bg: string; text: string; label: string } {
  if (rating == null) return { bg: "#F4F2F7", text: "#3B2D5E", label: "No rating" };
  if (rating < 3.8) return { bg: "#FFE3E9", text: "#8E1230", label: "Needs attention" };
  if (rating < 4.4) return { bg: "#FFF0CF", text: "#7A4B00", label: "Steady" };
  return { bg: "#DCF5E6", text: "#0E5C36", label: "Strong" };
}

export default function HeatmapGrid({ places }: { places: SavedPlace[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<PlaceDetails | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selected) { setDetails(null); return; }
    let dead = false;
    setLoading(true);
    getBenchmarkPlaceDetails(selected)
      .then((data) => { if (!dead) setDetails(data); })
      .catch(() => { if (!dead) setDetails(null); })
      .finally(() => { if (!dead) setLoading(false); });
    return () => { dead = true; };
  }, [selected]);

  return (
    <section aria-label="Market heatmap">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[14px] font-bold text-[#14101F]">Market heatmap</h2>
        <p className="text-[10px] text-[#3B2D5E]">
          Colour = rating · darker = more reviews
        </p>
      </div>

      {places.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-[32px] border border-dashed border-[#3D1D6E]/20 bg-white text-[12px] text-[#3B2D5E]">
          Save a business to see it on the heatmap.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {places.map((place) => {
            const tone = heatTone(place.rating);
            const volume = Math.min(1, Math.max(0.25, (place.review_count ?? 0) / 500));
            return (
              <button
                key={place.id}
                type="button"
                onClick={() => setSelected(place.place_id)}
                className={`flex min-h-[92px] flex-col justify-between rounded-[20px] border border-[#3D1D6E]/10 px-3 py-2.5 text-left transition hover:-translate-y-0.5 ${FOCUS}`}
                style={{ backgroundColor: tone.bg, boxShadow: `0 2px 0 rgba(20,16,31,${(volume * 0.12).toFixed(2)})` }}
                title={`${place.label || place.name || place.place_id} — ${tone.label}`}
              >
                <span className="truncate text-[11px] font-bold" style={{ color: tone.text }}>
                  {place.label || place.name || place.place_id}
                </span>
                <span className="font-mono text-[16px] font-bold" style={{ color: tone.text }}>
                  {place.rating != null ? place.rating.toFixed(1) : "—"}<span className="text-[10px]">★</span>
                </span>
                <span className="text-[9px] uppercase tracking-wide" style={{ color: tone.text }}>
                  {tone.label}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#14101F]/40 p-4" role="presentation" onClick={() => setSelected(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Business snapshot"
            className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-[32px] border border-[#3D1D6E]/15 bg-white p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-[16px] font-bold text-[#14101F]">
                  {details?.name || places.find((p) => p.place_id === selected)?.label || selected}
                </h3>
                <p className="mt-0.5 text-[11px] text-[#3B2D5E]">{details?.address}</p>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label="Close"
                className={`shrink-0 rounded-full border border-[#3D1D6E]/20 px-2.5 py-1 text-[12px] font-bold text-[#3B2D5E] ${FOCUS}`}
              >
                ×
              </button>
            </div>

            {loading ? (
              <p className="mt-5 text-[12px] text-[#3B2D5E]">Loading current details…</p>
            ) : details ? (
              <>
                <div className="mt-5 grid grid-cols-2 gap-3">
                  <div className="rounded-[20px] bg-[#F4F2F7] p-3">
                    <p className="text-[10px] uppercase tracking-wide text-[#3B2D5E]">Rating</p>
                    <p className="font-mono text-[20px] font-bold text-[#14101F]">
                      {details.rating != null ? details.rating.toFixed(1) : "—"}★
                    </p>
                  </div>
                  <div className="rounded-[20px] bg-[#F4F2F7] p-3">
                    <p className="text-[10px] uppercase tracking-wide text-[#3B2D5E]">Reviews</p>
                    <p className="font-mono text-[20px] font-bold text-[#14101F]">{details.review_count ?? "—"}</p>
                  </div>
                </div>

                <h4 className="mt-5 text-[12px] font-bold text-[#14101F]">Current reviews</h4>
                {details.reviews.length === 0 ? (
                  <p className="mt-2 text-[11px] text-[#3B2D5E]">No reviews returned by Google.</p>
                ) : (
                  <ul className="mt-2 divide-y divide-[#3D1D6E]/10">
                    {details.reviews.slice(0, 8).map((review, i) => (
                      <li key={i} className="py-2.5">
                        <p className="font-mono text-[11px] font-bold text-[#3D1D6E]">
                          {review.rating != null ? `${review.rating}★` : "—"}
                          {review.publish_time ? ` · ${review.publish_time.slice(0, 10)}` : ""}
                        </p>
                        <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-[#3B2D5E]">{review.text}</p>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-4 text-[10px] text-[#3B2D5E]">Business data from Google Maps</p>
              </>
            ) : (
              <p className="mt-5 text-[12px] text-red-700">Could not load current details.</p>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
