"use client";

import { useEffect, useState } from "react";
import {
  fetchInstagramAudience,
  type InstagramAudience,
  type InstagramDemographics,
  type InstagramPerson,
} from "@/lib/api-meta";

/*
 * Audience: who engaged with the account.
 *
 * NOT a follower list. Meta does not expose follower/following lists at all,
 * so this is built from the two sources that do have names: people who
 * commented (read live from Graph) and people who DMed you (from the inbox).
 * Every row therefore has a working instagram.com link - which is precisely
 * what a follower list could never give us, because no follower usernames are
 * available to anyone.
 *
 * The demographics panel is aggregate only, and says why when Meta has nothing
 * (missing insights scope, or under 100 followers) rather than showing blanks.
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

function Bar({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 2;
  return (
    <li>
      <div className="flex items-baseline justify-between gap-3">
        <span className={`text-[12px] ${INK}`}>{label}</span>
        <span className={`text-[12px] tabular-nums ${INK2}`}>{value.toLocaleString()}</span>
      </div>
      <div className="mt-1.5 h-2 w-full rounded-full bg-[var(--ui-sunken)]">
        <div
          className="h-2 rounded-full bg-[var(--ui-ink)]"
          style={{ width: `${pct}%` }}
          role="img"
          aria-label={`${label}: ${value}`}
        />
      </div>
    </li>
  );
}

function Breakdown({
  title,
  rows,
}: {
  title: string;
  rows: { label: string | null; value: number }[];
}) {
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => r.value));
  return (
    <div>
      <p className={`text-[12px] font-semibold ${INK2}`}>{title}</p>
      <ul className="mt-2 space-y-3">
        {rows.slice(0, 8).map((r) => (
          <Bar key={r.label ?? String(r.value)} label={r.label ?? "—"} value={r.value} max={max} />
        ))}
      </ul>
    </div>
  );
}

function Demographics({ demo }: { demo: InstagramDemographics }) {
  if (!demo.available) {
    return (
      <div>
        <h3 className={`text-[15px] font-semibold ${INK}`}>Follower demographics</h3>
        <p className={`mt-2 text-[13px] ${INK2}`}>
          {demo.reason || "Instagram has not shared follower demographics for this account yet."}
        </p>
      </div>
    );
  }
  const hasAny = demo.age.length + demo.gender.length + demo.cities.length + demo.countries.length > 0;
  if (!hasAny) {
    return (
      <div>
        <h3 className={`text-[15px] font-semibold ${INK}`}>Follower demographics</h3>
        <p className={`mt-2 text-[13px] ${INK2}`}>No demographic data returned yet.</p>
      </div>
    );
  }
  return (
    <div>
      <h3 className={`text-[15px] font-semibold ${INK}`}>Follower demographics</h3>
      <p className={`mt-1 text-[12px] ${INK2}`}>
        Instagram publishes these in aggregate only — counts by age, gender and location. It never
        shares who the individual followers are.
      </p>
      <div className="mt-4 grid gap-6 sm:grid-cols-2">
        <Breakdown title="Age" rows={demo.age} />
        <Breakdown title="Gender" rows={demo.gender} />
        <Breakdown title="Top cities" rows={demo.cities} />
        <Breakdown title="Top countries" rows={demo.countries} />
      </div>
    </div>
  );
}

function PersonRow({ person }: { person: InstagramPerson }) {
  const when = person.occurred_at ? new Date(person.occurred_at) : null;
  return (
    <li className="flex flex-wrap items-start gap-3 border-b border-[var(--ui-line)] py-3 last:border-0">
      <span
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)] text-[12px] font-bold text-[var(--ui-ink)]"
      >
        {(person.name || person.username || "?").trim().charAt(0).toUpperCase()}
      </span>
      <div className="min-w-[10rem] flex-1">
        <p className={`text-[13px] font-semibold ${INK}`}>
          {person.name || person.username || "Unknown"}
        </p>
        <p className={`text-[12px] ${INK2}`}>
          {person.username ? `@${person.username}` : "no username"}
          <span className="mx-1.5">·</span>
          {person.source === "comment" ? "commented" : "sent you a message"}
          {person.like_count > 0 && (
            <>
              <span className="mx-1.5">·</span>
              {person.like_count} like{person.like_count === 1 ? "" : "s"}
            </>
          )}
          {when && !Number.isNaN(when.getTime()) && (
            <>
              <span className="mx-1.5">·</span>
              {when.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </>
          )}
        </p>
        {person.text && (
          <p className={`mt-1 line-clamp-2 text-[12px] ${INK2}`}>{person.text}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {person.permalink && (
          <a
            href={person.permalink}
            target="_blank"
            rel="noopener noreferrer"
            className={`rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[12px] font-semibold ${INK}`}
          >
            Post
          </a>
        )}
        {person.profile_url ? (
          <a
            href={person.profile_url}
            target="_blank"
            rel="noopener noreferrer"
            className={`ui-btn rounded-lg bg-[var(--ui-ink)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-on-ink)]`}
          >
            Profile
          </a>
        ) : (
          <span className={`text-[12px] ${INK2}`}>No profile link</span>
        )}
      </div>
    </li>
  );
}

export default function AudienceTab({ igId }: { igId: string }) {
  const [data, setData] = useState<InstagramAudience | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchInstagramAudience(igId).then(
      (d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
          setLoading(false);
        }
      },
      (e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load your audience.");
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [igId]);

  if (loading) return <p className={`text-[13px] ${INK2}`}>Loading your audience…</p>;

  if (error) {
    return (
      <div role="alert" className={`rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4`}>
        <p className={`text-[13px] font-bold ${INK}`}>{error}</p>
      </div>
    );
  }

  const people = data?.people ?? [];

  return (
    <div className="space-y-6">
      <section className={PANEL}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className={`text-[15px] font-semibold ${INK}`}>People who engaged</h3>
          <span className={`text-[12px] ${INK2}`}>{people.length} people</span>
        </div>
        <p className={`mt-1 text-[12px] ${INK2}`}>
          Instagram does not share follower lists, so this is everyone who actually reached out:
          people who commented on your posts and people who messaged you.
        </p>

        {data?.comments_unavailable && (
          <p className={`mt-4 rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] ${INK2}`}>
            {data.comments_unavailable}
          </p>
        )}

        {people.length === 0 ? (
          <p className={`mt-4 text-[13px] ${INK2}`}>
            Nobody has commented or messaged yet. Once they do, they show up here.
          </p>
        ) : (
          <ul className="mt-4">
            {people.map((p, i) => (
              <PersonRow key={`${p.source}-${p.ig_id ?? i}-${i}`} person={p} />
            ))}
          </ul>
        )}
      </section>

      <section className={PANEL}>
        <Demographics demo={data!.demographics} />
      </section>
    </div>
  );
}