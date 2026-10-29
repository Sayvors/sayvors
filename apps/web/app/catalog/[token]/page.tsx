"use client";

/* Public catalog page: no session, no dashboard chrome.
 *
 * The URL token is the whole credential, so the page reveals exactly what the
 * API chooses to expose — names, prices, stock — and nothing else.
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { API_BASE } from "@/lib/api-base";
import type { PublicCatalog, PublicCatalogItem } from "@/lib/api-catalog";

function Price({ item }: { item: PublicCatalogItem }) {
  if (!item.price_display) return null;
  return (
    <span className="text-[15px] font-semibold text-ink dark:text-fog">
      {item.price_display}
    </span>
  );
}

function Stock({ item }: { item: PublicCatalogItem }) {
  if (item.in_stock) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald">
        In stock
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50">
      Out of stock
    </span>
  );
}

function Card({ item }: { item: PublicCatalogItem }) {
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <article className="overflow-hidden rounded-[28px] border border-ink/[0.06] bg-white shadow-[0_1px_2px_rgba(20,16,31,0.04),0_12px_28px_-18px_rgba(20,16,31,0.25)] dark:border-fog/[0.08] dark:bg-ink">
      {item.image_url && !imageFailed ? (
        // Plain img: the catalog stores arbitrary tenant URLs, which next/image
        // would need every remote host pre-registered for.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.image_url}
          alt={item.name}
          className="h-44 w-full bg-fog object-cover dark:bg-fog/[0.06]"
          loading="lazy"
          // A dead image host must not leave a broken glyph in a customer's
          // catalog; fall back to the plain accent bar.
          onError={() => setImageFailed(true)}
        />
      ) : (
        <div className="h-2 w-full bg-deep-violet/80" aria-hidden="true" />
      )}
      <div className="flex flex-col gap-2 p-5">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-[15px] font-semibold leading-snug text-ink dark:text-fog">
            {item.name}
          </h2>
          <Price item={item} />
        </div>
        {item.description ? (
          <p className="text-[12.5px] leading-5 text-ink/60 dark:text-fog/60">
            {item.description}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Stock item={item} />
          {!item.in_stock && item.availability_note ? (
            <span className="text-[11px] text-ink/45 dark:text-fog/45">
              {item.availability_note}
            </span>
          ) : null}
          {item.item_url ? (
            <a
              href={item.item_url}
              target="_blank"
              rel="noreferrer noopener"
              className="ml-auto rounded-full border border-deep-violet/25 px-3 py-1 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/10 dark:border-fog/20 dark:text-fog"
            >
              View
            </a>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export default function PublicCatalogPage() {
  const params = useParams<{ token: string }>();
  const token = typeof params?.token === "string" ? params.token : "";
  const [data, setData] = useState<PublicCatalog | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");

  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setState("missing");
      return;
    }
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/catalog/public/${encodeURIComponent(token)}`,
        );
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as PublicCatalog;
        if (!cancelled) {
          setData(body);
          setState("ready");
        }
      } catch {
        if (!cancelled) setState("missing");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <main className="min-h-screen bg-[#f1f2f5] px-4 py-10 dark:bg-[#0f0b18] sm:px-6 sm:py-14">
      <div className="mx-auto w-full max-w-5xl">
        {state === "loading" ? (
          <div className="py-24 text-center text-[13px] text-ink/40 dark:text-fog/40">
            Loading catalog…
          </div>
        ) : state === "missing" ? (
          <div className="rounded-[28px] bg-white p-10 text-center shadow-[0_1px_2px_rgba(20,16,31,0.04),0_18px_40px_-24px_rgba(20,16,31,0.3)] dark:bg-ink">
            <h1 className="text-[18px] font-semibold text-ink dark:text-fog">
              This catalog link is not available
            </h1>
            <p className="mt-2 text-[13px] text-ink/50 dark:text-fog/50">
              It may have been replaced or turned off. Ask the business for a
              fresh link.
            </p>
          </div>
        ) : (
          <>
            <header className="mb-8">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-deep-violet dark:text-fog/50">
                Catalog
              </p>
              <h1 className="mt-1 text-[26px] font-semibold tracking-tight text-ink dark:text-fog">
                {data?.business_name}
              </h1>
              {data?.items.length ? (
                <p className="mt-1 text-[13px] text-ink/50 dark:text-fog/50">
                  {data.items.length} item{data.items.length === 1 ? "" : "s"}
                </p>
              ) : null}
            </header>

            {data?.items.length ? (
              <div className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {data.items.map((item) => (
                  <Card key={`${item.name}-${item.price_display ?? ""}`} item={item} />
                ))}
              </div>
            ) : (
              <div className="rounded-[28px] bg-white p-10 text-center text-[13px] text-ink/50 shadow-[0_1px_2px_rgba(20,16,31,0.04),0_18px_40px_-24px_rgba(20,16,31,0.3)] dark:bg-ink dark:text-fog/50">
                No items are listed yet.
              </div>
            )}

            <p className="mt-10 text-center text-[11px] text-ink/35 dark:text-fog/35">
              Prices are set by the business and may change.
            </p>
          </>
        )}
      </div>
    </main>
  );
}
