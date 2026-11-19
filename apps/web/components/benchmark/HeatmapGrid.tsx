"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import { getBenchmarkPlaceDetails, type PlaceDetails } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";

interface Matrix {
  weeks: string[];
  metric: "reviews";
  rows: {
    place_id: string;
    external_id: string;
    name: string;
    rating: number | null;
    cells: (number | null)[];
  }[];
}

/** Five-step solid colour scale — no gradients, density by review volume. */
function cellColor(value: number | null): string {
  if (value == null) return "#F4F2F7";
  if (value <= 0) return "#F4F2F7";
  if (value < 10) return "#FFF0CF";
  if (value < 50) return "#FFD8A8";
  if (value < 200) return "#F7A9BD";
  return "#B0338A";
}

export default function HeatmapGrid() {
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<PlaceDetails | null>(null);
  const [loading, setLoading] = useState(false);

  const matrixQuery = useQuery({
    queryKey: ["benchmark", "heatmap"],
    queryFn: () => apiFetch("/api/v1/benchmark/heatmap?weeks=12") as Promise<Matrix>,
  });
  const matrix = matrixQuery.data;

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
          Each row is a saved business · each column a week · colour = review volume
        </p>
      </div>

      {matrixQuery.isPending ? (
        <p className="text-[12px] text-[#3B2D5E]">Loading heatmap…</p>
      ) : !matrix || matrix.rows.length === 0 ? (
        <div className="flex h-40 items-center justify-center rounded-[12px] border border-dashed border-[#3D1D6E]/20 bg-white text-[12px] text-[#3B2D5E]">
          No saved businesses on the heatmap yet. Add one from your bench or your own locations.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[12px] border border-[var(--ui-line)] bg-white">
          <table className="w-full min-w-[760px] border-collapse text-[10px]">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-white px-3 py-2 text-left font-semibold text-[#3B2D5E]">
                  Business
                </th>
                {matrix.weeks.map((week) => (
                  <th key={week} className="px-1 py-2 text-center font-mono font-medium text-[#3B2D5E]">
                    {week.slice(5)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.rows.map((row) => (
                <tr key={row.place_id} className="border-t border-[var(--ui-line)]">
                  <th className="sticky left-0 z-10 max-w-[180px] truncate bg-white px-3 py-1.5 text-left font-semibold text-[#14101F]">
                    <button
                      type="button"
                      onClick={() => setSelected(row.external_id)}
                      className={`truncate hover:underline ${FOCUS}`}
                      title={row.name}
                    >
                      {row.name}
                    </button>
                  </th>
                  {row.cells.map((value, index) => (
                    <td key={index} className="px-1 py-1.5 text-center">
                      <button
                        type="button"
                        onClick={() => setSelected(row.external_id)}
                        aria-label={`${row.name}, week ${matrix.weeks[index]}: ${value ?? "no data"}`}
                        title={`${row.name} · ${matrix.weeks[index]} · ${value ?? "no data"}`}
                        className={`h-6 w-full min-w-[22px] rounded-[4px] border border-[#3D1D6E]/10 ${FOCUS}`}
                        style={{ backgroundColor: cellColor(value) }}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-2 flex items-center gap-2 text-[10px] text-[#3B2D5E]">
        <span>Less</span>
        {[0, 5, 10, 50, 200].map((v) => (
          <span key={v} className="h-3 w-5 rounded-[4px] border border-[#3D1D6E]/10" style={{ backgroundColor: cellColor(v) }} />
        ))}
        <span>More</span>
      </div>

      {selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#14101F]/40 p-4" role="presentation" onClick={() => setSelected(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Business snapshot"
            className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-[12px] border border-[#3D1D6E]/15 bg-white p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-[16px] font-bold text-[#14101F]">
                  {details?.name || matrix?.rows.find((r) => r.external_id === selected)?.name || selected}
                </h3>
                <p className="mt-0.5 text-[11px] text-[#3B2D5E]">{details?.address}</p>
              </div>
              <button type="button" onClick={() => setSelected(null)} aria-label="Close"
                className={`shrink-0 rounded-full border border-[#3D1D6E]/20 px-2.5 py-1 text-[12px] font-bold text-[#3B2D5E] ${FOCUS}`}>
                ×
              </button>
            </div>
            {loading ? (
              <p className="mt-5 text-[12px] text-[#3B2D5E]">Loading current details…</p>
            ) : details ? (
              <>
                <div className="mt-5 grid grid-cols-2 gap-3">
                  <div className="rounded-[10px] bg-[#F4F2F7] p-3">
                    <p className="text-[10px] uppercase tracking-wide text-[#3B2D5E]">Rating</p>
                    <p className="font-mono text-[20px] font-bold text-[#14101F]">
                      {details.rating != null ? details.rating.toFixed(1) : "—"}★
                    </p>
                  </div>
                  <div className="rounded-[10px] bg-[#F4F2F7] p-3">
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
