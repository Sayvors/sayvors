"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { loadGoogleMaps } from "@/lib/google-maps";
import type { SavedPlace } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[#3D1D6E]";
const DEFAULT_ZOOM = 11;
const MIN_HEAT_WEIGHT = 1;

type MapLoadState = "loading" | "ready" | "error";
type MapState = MapLoadState | "nokey" | "nocoords";

function locatedPlaces(places: SavedPlace[]): SavedPlace[] {
  return places.filter(
    (place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude),
  );
}

function infoContent(place: SavedPlace): HTMLDivElement {
  const content = document.createElement("div");
  content.style.cssText = "font:12px/1.5 system-ui;color:#14101F;max-width:260px";

  const title = document.createElement("strong");
  title.textContent = place.label || place.name || place.place_id;
  content.append(title);

  if (place.address) {
    const address = document.createElement("div");
    address.style.color = "#6F6685";
    address.textContent = place.address;
    content.append(address);
  }

  const facts = document.createElement("div");
  facts.style.marginTop = "6px";
  facts.textContent = [
    place.rating != null ? `${place.rating.toFixed(1)}★` : "No rating",
    place.review_count != null ? `${place.review_count} reviews` : "",
  ].filter(Boolean).join(" · ");
  content.append(facts);
  return content;
}

/** Real map for saved benchmark places; density is weighted by review volume. */
export default function BenchmarkMap({
  places,
  apiKey,
  onRetry,
}: {
  places: SavedPlace[];
  apiKey: string;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const mountRef = useRef<HTMLDivElement | null>(null);
  const markersRef = useRef<any[]>([]);
  const heatmapRef = useRef<any | null>(null);
  const [attempt, setAttempt] = useState(0);
  const located = useMemo(() => locatedPlaces(places), [places]);
  const [loadState, setLoadState] = useState<MapLoadState>("loading");
  const state: MapState = !apiKey
    ? "nokey"
    : located.length === 0
      ? "nocoords"
      : loadState;

  useEffect(() => {
    if (!apiKey || located.length === 0) return;

    let cancelled = false;

    void (async () => {
      setLoadState("loading");
      try {
        await loadGoogleMaps(apiKey);
        if (cancelled || !mountRef.current) return;
        const google = (window as any).google;
        const first = located[0];
        const map = new google.maps.Map(mountRef.current, {
          center: { lat: first.latitude!, lng: first.longitude! },
          zoom: DEFAULT_ZOOM,
          mapId: "DEMO_MAP_ID",
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: true,
          clickableIcons: false,
        });

        const infoWindow = new google.maps.InfoWindow();
        const markers = located.map((place) => {
          const marker = new google.maps.Marker({
            map,
            position: { lat: place.latitude!, lng: place.longitude! },
            title: place.label || place.name || place.place_id,
          });
          marker.addListener("click", () => {
            infoWindow.setContent(infoContent(place));
            infoWindow.open({ map, anchor: marker });
          });
          return marker;
        });
        markersRef.current = markers;

        const heatmap = new google.maps.visualization.HeatmapLayer({
          map,
          data: located.map((place) => ({
            location: new google.maps.LatLng(place.latitude!, place.longitude!),
            weight: Math.max(MIN_HEAT_WEIGHT, place.review_count ?? MIN_HEAT_WEIGHT),
          })),
        });
        heatmapRef.current = heatmap;

        if (located.length > 1) {
          const bounds = new google.maps.LatLngBounds();
          located.forEach((place) =>
            bounds.extend({ lat: place.latitude!, lng: place.longitude! }),
          );
          map.fitBounds(bounds, 80);
        }
        setLoadState("ready");
      } catch {
        if (!cancelled) setLoadState("error");
      }
    })();

    return () => {
      cancelled = true;
      markersRef.current.forEach((marker) => marker.setMap(null));
      markersRef.current = [];
      heatmapRef.current?.setMap(null);
      heatmapRef.current = null;
    };
  }, [apiKey, located, attempt]);

  if (state === "nokey" || state === "nocoords") {
    return (
      <section className="rounded-[8px] border border-[var(--ui-line)] bg-white p-5">
        <h3 className="text-[13px] font-bold text-[#14101F]">{b.heatmapMapTitle}</h3>
        <p className="mt-2 text-[12px] text-[#3B2D5E]">
          {state === "nokey" ? b.heatmapMapNoKey : b.heatmapMapNoLocations}
        </p>
      </section>
    );
  }

  return (
    <section className="overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--ui-line)] px-4 py-3">
        <div>
          <h3 className="text-[13px] font-bold text-[#14101F]">{b.heatmapMapTitle}</h3>
          <p className="mt-0.5 text-[11px] text-[#3B2D5E]">
            {state === "ready" ? b.heatmapMapReady(located.length) : b.heatmapMapLoading}
          </p>
        </div>
        <p className="text-[10px] text-[#6F6685]">{b.heatmapMapCaption}</p>
      </header>
      <div className="relative">
        <div
          ref={mountRef}
          role="region"
          aria-label={b.heatmapMapTitle}
          className="h-[420px] w-full bg-[#F1F2F5]"
        />
        {state === "loading" ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70">
            <span role="status" className="text-[12px] font-semibold text-[#3B2D5E]">
              {b.heatmapMapLoading}
            </span>
          </div>
        ) : null}
        {state === "error" ? (
          <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white/90 p-6 text-center">
            <p className="text-[12px] font-semibold text-[#B3123A]">{b.heatmapMapError}</p>
            <button
              type="button"
              onClick={() => {
                setAttempt((value) => value + 1);
                onRetry?.();
              }}
              className={`inline-flex min-h-11 items-center rounded-[8px] border border-[#3D1D6E]/25 bg-white px-3 text-[11px] font-bold text-[#3D1D6E] ${FOCUS}`}
            >
              {t.common.retry}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
