"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { loadGoogleMaps } from "@/lib/google-maps";

/* eslint-disable @typescript-eslint/no-explicit-any */

const FALLBACK = { lat: 24.7136, lng: 46.6753 };

export interface LatLng {
  lat: number;
  lng: number;
}

/**
 * Draggable address pin for the create-location wizard.
 *
 * The pin is optional: Google geocodes the structured address on create and
 * ignores `latlng` when that succeeds. It exists for the cases where the
 * address is ambiguous (malls, compounds, new streets) and Google asks for a
 * precise pin.
 */
export default function LocationPinMap({
  apiKey,
  address,
  value,
  onChange,
}: {
  apiKey: string;
  address: string;
  value: LatLng | null;
  onChange: (next: LatLng | null) => void;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const geocoderRef = useRef<any>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const [state, setState] = useState<"loading" | "ready" | "error" | "nokey">(
    apiKey ? "loading" : "nokey",
  );
  const [note, setNote] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  const placeMarker = useCallback((position: LatLng, center = false) => {
    const g = (window as unknown as { google?: any }).google;
    if (!g?.maps || !mapRef.current) return;
    if (!markerRef.current) {
      markerRef.current = new g.maps.Marker({
        map: mapRef.current,
        position,
        draggable: true,
        title: "Business location",
      });
      markerRef.current.addListener("dragend", () => {
        const point = markerRef.current?.getPosition();
        if (point) onChangeRef.current({ lat: point.lat(), lng: point.lng() });
      });
    } else {
      markerRef.current.setPosition(position);
    }
    if (center) mapRef.current.setCenter(position);
  }, []);

  useEffect(() => {
    if (!apiKey) {
      setState("nokey");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await loadGoogleMaps(apiKey);
        if (cancelled || !mountRef.current) return;
        const g = (window as unknown as { google?: any }).google;
        if (!g?.maps) throw new Error("Maps unavailable");
        mapRef.current = new g.maps.Map(mountRef.current, {
          center: value ?? FALLBACK,
          zoom: value ? 16 : 11,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
        });
        geocoderRef.current = new g.maps.Geocoder();
        if (value) placeMarker(value, true);
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
    // `value` is only the initial centre; later changes flow through the
    // marker effect below, so this must not re-create the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  useEffect(() => {
    if (state !== "ready") return;
    if (value) {
      placeMarker(value);
      return;
    }
    if (markerRef.current) {
      markerRef.current.setMap(null);
      markerRef.current = null;
    }
  }, [value, state, placeMarker]);

  const locate = useCallback(() => {
    const g = (window as unknown as { google?: any }).google;
    if (!g?.maps || !geocoderRef.current || !address.trim()) return;
    setLocating(true);
    setNote(null);
    geocoderRef.current.geocode(
      { address },
      (results: any[] | null, status: string) => {
        setLocating(false);
        if (status !== "OK" || !results?.[0]?.geometry?.location) {
          setNote("Google could not find that address. Drag the pin manually.");
          return;
        }
        const point = results[0].geometry.location;
        const next = { lat: point.lat(), lng: point.lng() };
        placeMarker(next, true);
        onChangeRef.current(next);
      },
    );
  }, [address, placeMarker]);

  if (!apiKey) {
    return (
      <div className="rounded-xl border border-dashed border-ink/15 bg-ink/[0.02] p-4 text-[12px] leading-relaxed text-ink/55 dark:border-fog/15 dark:bg-fog/[0.02] dark:text-fog/55">
        Map pin is unavailable because <code>NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code> is not set.
        You can still create the location; Google will geocode the address.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div
        ref={mountRef}
        className="h-[280px] w-full overflow-hidden rounded-xl border border-ink/[0.08] dark:border-fog/[0.08]"
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-ink/45 dark:text-fog/45">
          {state === "loading"
            ? "Loading map..."
            : state === "error"
              ? "Map could not load."
              : "Drag the pin to the exact entrance."}
        </p>
        <button
          type="button"
          onClick={locate}
          disabled={locating || state !== "ready"}
          className="rounded-lg border border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/65 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:border-fog/10 dark:text-fog/65"
        >
          {locating ? "Locating..." : "Locate address"}
        </button>
      </div>
      {note && <p className="text-[11px] text-amber-700 dark:text-amber-300">{note}</p>}
      {value && (
        <p className="text-[10.5px] text-ink/40 dark:text-fog/40">
          Pin: {value.lat.toFixed(6)}, {value.lng.toFixed(6)}
        </p>
      )}
    </div>
  );
}
