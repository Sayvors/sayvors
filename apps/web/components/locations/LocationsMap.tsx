"use client";

import { useEffect, useRef, useState } from "react";

/* eslint-disable @typescript-eslint/no-explicit-any */

const RIYADH = { lat: 24.7136, lng: 46.6753 };
const MAPS_SCRIPT_ID = "sayvors-google-maps";
const GEO_CACHE_PREFIX = "sayvors.geo.";

export interface MapLocation {
  id: string;
  name: string;
  address: string;
  rating?: number | null;
  reviews?: number | null;
}

interface Geocoded extends MapLocation {
  position: { lat: number; lng: number };
  approximate: boolean;
}

let scriptPromise: Promise<void> | null = null;

function loadMaps(apiKey: string): Promise<void> {
  const w = window as unknown as { google?: any };
  if (w.google?.maps) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(MAPS_SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Maps script failed")));
      return;
    }
    const script = document.createElement("script");
    script.id = MAPS_SCRIPT_ID;
    script.async = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&v=weekly&libraries=marker,geometry`;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Maps script failed"));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** A quadratic arc in lat/lng, bent to one side so lines do not overlap. */
function arcPath(a: { lat: number; lng: number }, b: { lat: number; lng: number }, bend = 0.22) {
  const mid = { lat: (a.lat + b.lat) / 2, lng: (a.lng + b.lng) / 2 };
  const dx = b.lng - a.lng;
  const dy = b.lat - a.lat;
  const control = { lat: mid.lat - dx * bend, lng: mid.lng + dy * bend };
  const points: { lat: number; lng: number }[] = [];
  for (let i = 0; i <= 24; i++) {
    const t = i / 24;
    points.push({
      lat: (1 - t) * (1 - t) * a.lat + 2 * (1 - t) * t * control.lat + t * t * b.lat,
      lng: (1 - t) * (1 - t) * a.lng + 2 * (1 - t) * t * control.lng + t * t * b.lng,
    });
  }
  return points;
}

function fallbackPosition(index: number) {
  // Deterministic small offset so an ungeocoded listing still appears near
  // Riyadh instead of vanishing. The popup says "approximate".
  const angle = (index * 137.5 * Math.PI) / 180;
  const r = 0.03 + (index % 5) * 0.012;
  return { lat: RIYADH.lat + Math.sin(angle) * r, lng: RIYADH.lng + Math.cos(angle) * r };
}

export default function LocationsMap({
  locations,
  apiKey,
}: {
  locations: MapLocation[];
  apiKey: string;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const [state, setState] = useState<"loading" | "ready" | "error" | "nokey">(
    apiKey ? "loading" : "nokey"
  );
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!apiKey) {
      setState("nokey");
      return;
    }
    let cancelled = false;

    (async () => {
      try {
        await loadMaps(apiKey);
        if (cancelled || !mountRef.current) return;
        const g = (window as unknown as { google: any }).google;

        const map = new g.maps.Map(mountRef.current, {
          center: RIYADH,
          zoom: 10,
          // Advanced markers require a map id; DEMO_MAP_ID is Google's
          // documented development id.
          mapId: "DEMO_MAP_ID",
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: true,
          rotateControl: true,
          tilt: 45,
          heading: 0,
          gestureHandling: "greedy",
          clickableIcons: false,
        });
        mapRef.current = map;

        const geocoder = new g.maps.Geocoder();
        const geocoded: Geocoded[] = [];
        for (let i = 0; i < locations.length; i++) {
          const loc = locations[i];
          const cacheKey = `${GEO_CACHE_PREFIX}${loc.address || loc.name}`;
          let position: { lat: number; lng: number } | null = null;
          let approximate = false;
          try {
            const cached = sessionStorage.getItem(cacheKey);
            if (cached) {
              position = JSON.parse(cached) as { lat: number; lng: number };
            } else if (loc.address || loc.name) {
              const res = await geocoder.geocode({ address: loc.address || loc.name });
              const first = res?.results?.[0]?.geometry?.location;
              if (first) {
                position = { lat: first.lat(), lng: first.lng() };
                sessionStorage.setItem(cacheKey, JSON.stringify(position));
              }
            }
          } catch {
            position = null;
          }
          if (!position) {
            position = fallbackPosition(i);
            approximate = true;
          }
          geocoded.push({ ...loc, position, approximate });
        }

        // Sayvors HQ marker.
        const hq = new g.maps.marker.AdvancedMarkerElement({
          map,
          position: RIYADH,
          title: "Sayvors HQ",
          zIndex: 10,
          content: (() => {
            const el = document.createElement("div");
            el.style.cssText =
              "display:flex;align-items:center;gap:6px;background:#14101F;color:#fff;border-radius:999px;padding:6px 10px;font:700 11px/1 system-ui;box-shadow:0 8px 24px rgba(20,16,31,.35);border:2px solid #fff";
            el.innerHTML = "<span style='width:8px;height:8px;border-radius:99px;background:#B0338A;display:inline-block'></span>Sayvors · Riyadh";
            return el;
          })(),
        });
        hq.addListener("gmp-click", () => {
          const info = new g.maps.InfoWindow({
            content:
              "<div style='font:12px/1.4 system-ui;color:#14101F'><strong>Sayvors</strong><br/>Riyadh, Saudi Arabia<br/><span style='color:#6b6478'>Managing your locations</span></div>",
          });
          info.open({ map, anchor: hq });
        });

        // Listing markers + arcs.
        geocoded.forEach((loc, idx) => {
          const el = document.createElement("div");
          el.style.cssText =
            "display:flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:14px;background:#fff;color:#3D1D6E;font:800 12px/1 system-ui;border:2px solid #3D1D6E;box-shadow:0 6px 18px rgba(61,29,110,.28);cursor:pointer;transform:rotate(-2deg)";
          el.textContent = initials(loc.name || "L");
          el.title = loc.name;

          const marker = new g.maps.marker.AdvancedMarkerElement({
            map,
            position: loc.position,
            content: el,
            title: loc.name,
            zIndex: 20 + idx,
          });
          marker.addListener("gmp-click", () => {
            const rating = loc.rating !== null && loc.rating !== undefined ? `${loc.rating.toFixed(1)}★` : "No rating";
            const reviews = loc.reviews !== null && loc.reviews !== undefined ? `${loc.reviews} reviews` : "";
            const info = new g.maps.InfoWindow({
              content: `<div style='font:12px/1.45 system-ui;color:#14101F;max-width:240px'>
                <strong>${escapeHtml(loc.name)}</strong><br/>
                <span style='color:#6b6478'>${escapeHtml(loc.address || "")}</span><br/>
                <span style='display:inline-block;margin-top:6px;padding:2px 6px;border-radius:4px;background:#F4F2F7;font-weight:700'>${rating}</span>
                ${reviews ? `<span style='margin-left:6px;color:#6b6478'>${reviews}</span>` : ""}
                ${loc.approximate ? `<div style='margin-top:6px;color:#9a8fae;font-size:10px'>Approximate location</div>` : ""}
              </div>`,
            });
            info.open({ map, anchor: marker });
          });

          const line = new g.maps.Polyline({
            map,
            path: arcPath(RIYADH, loc.position),
            strokeColor: "#3D1D6E",
            strokeOpacity: 0.45,
            strokeWeight: 2,
            geodesic: false,
          });
          // Keep the line reference alive with the marker lifetime.
          (marker as unknown as { _sayvorsLine?: unknown })._sayvorsLine = line;
        });

        if (geocoded.length > 0) {
          const bounds = new g.maps.LatLngBounds();
          bounds.extend(RIYADH);
          geocoded.forEach((l) => bounds.extend(l.position));
          map.fitBounds(bounds, 80);
        }
        setCount(geocoded.length);
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [apiKey, locations]);

  const resetView = () => {
    const map = mapRef.current;
    if (!map) return;
    map.setHeading(0);
    map.setTilt(45);
    map.setZoom(10);
    map.panTo(RIYADH);
  };

  if (state === "nokey") {
    return (
      <section aria-label="Locations map" className="ui-card p-5">
        <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Locations map</h3>
        <p className="mt-2 text-[12px] text-[var(--ui-ink-2)]">
          Map not connected. Add <code>NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code> (restricted by HTTP referrer) to show Sayvors HQ, your listings, and the arcs between them.
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Locations map" className="ui-card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--ui-line)] px-4 py-3">
        <div>
          <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">Locations map</h3>
          <p className="text-[11px] text-[var(--ui-ink-2)]">
            {state === "ready" ? `${count} listing${count === 1 ? "" : "s"} connected to Sayvors · Riyadh` : "Preparing map…"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={resetView} className="rounded-[2px] border border-[var(--ui-line)] px-2.5 py-1.5 text-[10px] font-semibold text-[var(--ui-ink)] hover:bg-[var(--ui-sunken)]">
            Reset view
          </button>
          <span className="hidden text-[10px] text-[var(--ui-ink-2)] sm:inline">Drag to pan · scroll to zoom · right-drag to rotate</span>
        </div>
      </div>
      <div className="relative">
        <div ref={mountRef} className="h-[460px] w-full bg-[var(--ui-sunken)]" />
        {state === "loading" && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--ui-sunken)]/70">
            <span className="text-[12px] text-[var(--ui-ink-2)]">Loading map…</span>
          </div>
        )}
        {state === "error" && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--ui-sunken)]/80 p-6 text-center">
            <p className="text-[12px] text-[var(--ui-ink-2)]">
              Could not load Google Maps. Check the API key, referrer restrictions, and that the Maps JavaScript API is enabled.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
