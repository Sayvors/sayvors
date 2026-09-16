"use client";

import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { TOUR_STEPS } from "@/lib/tour/steps";

const STORAGE_KEY = "sayvors.tour";

type TourPhase = "idle" | "welcome" | "active";

interface TourContextValue {
  /** Start the guided tour from the first step (skips the welcome modal). */
  startTour: () => void;
}

const TourContext = createContext<TourContextValue>({ startTour: () => {} });

export function useTour() {
  return useContext(TourContext);
}

export default function TourProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [phase, setPhase] = useState<TourPhase>("idle");
  const driverRef = useRef<Driver | null>(null);
  const stepRef = useRef(0);
  const timersRef = useRef<number[]>([]);
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;
  // Mirror of showStep so the long-lived driver callbacks always reach the
  // latest closure (pathname changes across tour navigation).
  const showStepRef = useRef<(index: number) => void>(() => {});

  const later = useCallback((fn: () => void, ms: number) => {
    const id = window.setTimeout(fn, ms);
    timersRef.current.push(id);
  }, []);

  const clearTimers = useCallback(() => {
    for (const id of timersRef.current) window.clearTimeout(id);
    timersRef.current = [];
  }, []);

  /** Wait (up to ~3s) for a cross-page element to appear after navigation. */
  const waitFor = useCallback(
    (selector: string | null): Promise<Element | null> =>
      new Promise((resolve) => {
        if (!selector) return resolve(null);
        const started = Date.now();
        const tick = () => {
          const el = document.querySelector(selector);
          if (el) return resolve(el);
          if (Date.now() - started > 3000) return resolve(null);
          later(tick, 120);
        };
        tick();
      }),
    [later]
  );

  const persist = useCallback((state: "done" | "skipped") => {
    try {
      window.localStorage.setItem(STORAGE_KEY, state);
    } catch {
      /* private mode — tour just re-offers next visit */
    }
  }, []);

  const endTour = useCallback(
    (state: "done" | "skipped") => {
      clearTimers();
      stepRef.current = 0;
      try {
        if (driverRef.current?.isActive()) driverRef.current.destroy();
      } catch {
        /* already gone */
      }
      driverRef.current = null;
      persist(state);
      setPhase("idle");
    },
    [clearTimers, persist]
  );

  const showStep = useCallback(
    (index: number) => {
      if (index >= TOUR_STEPS.length) {
        endTour("done");
        return;
      }
      stepRef.current = index;
      const step = TOUR_STEPS[index];
      const go = async () => {
        if (step.route !== pathnameRef.current) {
          router.push(step.route);
        }
        const el = await waitFor(step.selector);
        if (!driverRef.current) {
          driverRef.current = driver({
            popoverClass: "sayvors-tour-popover",
            allowClose: false,
            nextBtnText: "Next",
            prevBtnText: "Skip & exit",
            showButtons: ["next", "previous"],
            disableActiveInteraction: false,
            onNextClick: () => {
              if (stepRef.current + 1 >= TOUR_STEPS.length) endTour("done");
              else showStepRef.current(stepRef.current + 1);
            },
            onPrevClick: () => endTour("skipped"),
          });
        }
        driverRef.current.highlight({
          ...(el ? { element: el } : {}),
          popover: {
            title: `${index + 1}/${TOUR_STEPS.length} · ${step.title}`,
            description: step.body,
            // NOTE: driver.js `highlight()` forces showButtons: [] — the
            // global config is ignored on this path, so repeat it here.
            showButtons: ["next", "previous"],
          },
        });
      };
      void go();
    },
    [router, waitFor, endTour]
  );
  showStepRef.current = showStep;

  const startTour = useCallback(() => {
    clearTimers();
    try {
      if (driverRef.current?.isActive()) driverRef.current.destroy();
    } catch {
      /* already gone */
    }
    driverRef.current = null;
    setPhase("active");
    // Let the welcome modal unmount before spotlighting.
    later(() => showStepRef.current(0), 60);
  }, [clearTimers, later]);

  /* First visit: offer the tour once. */
  useEffect(() => {
    let seen: string | null = null;
    try {
      seen = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      /* private mode */
    }
    if (!seen) setPhase("welcome");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- offer once per full page load
  }, []);

  useEffect(
    () => () => {
      clearTimers();
      try {
        driverRef.current?.destroy();
      } catch {
        /* already gone */
      }
      driverRef.current = null;
    },
    [clearTimers]
  );

  const skip = () => endTour("skipped");

  return (
    <TourContext.Provider value={{ startTour }}>
      {children}

      {/* Welcome (first visit) */}
      {phase === "welcome" && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-ink/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Welcome to Sayvors">
          <div className="w-full max-w-sm rounded-3xl border-2 border-white bg-white p-6 text-center shadow-[0_18px_50px_rgba(58,39,120,0.25)] dark:border-fog/[0.1] dark:bg-ink">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/Sayvors_Icon.png" alt="" className="mx-auto h-12 w-12 rounded-xl" />
            <h2 className="mt-3 text-[17px] font-bold text-ink dark:text-fog">Welcome to Sayvors 👋</h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink/55 dark:text-fog/55">
              Take a 1-minute tour: connect your Google location, sync reviews,
              and see where AI replies wait for your approval.
            </p>
            <div className="mt-5 flex items-center justify-center gap-2">
              <button
                onClick={skip}
                className="rounded-xl px-4 py-2.5 text-[12.5px] font-semibold text-ink/50 outline-none transition hover:bg-ink/[0.04] hover:text-ink focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/50 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
              >
                Skip & exit
              </button>
              <button
                onClick={startTour}
                className="rounded-xl bg-deep-violet px-5 py-2.5 text-[12.5px] font-bold text-white shadow-sm shadow-deep-violet/25 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-[0.98]"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </TourContext.Provider>
  );
}
