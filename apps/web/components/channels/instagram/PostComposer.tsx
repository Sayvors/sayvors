"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchInstagramLocations,
  fetchInstagramPublishingLimit,
  publishToInstagram,
  suggestInstagramCaption,
  type InstagramLocation,
} from "@/lib/api-meta";
import { apiFetch } from "@/lib/api-rag";
import PlatformMark from "@/components/channels/PlatformMark";
import CropEditor, {
  CROP_RATIOS,
  STORY_RATIO,
  centerCropBlob,
  type CropRatio,
} from "./CropEditor";
import { INK, INK2 } from "./ui";

/*
 * Publish to the tenant's OWN Instagram feed — the way the Instagram app
 * does it, minus what Meta's API refuses to do.
 *
 * Every control here maps to a real container parameter: crop ratios are
 * the client-side answer to Meta cropping carousel images itself, stories
 * are media_type=STORIES (9:16 only — we auto-crop the first image),
 * location is a Facebook place id, share_to_facebook cross-posts to the
 * linked Page, alt_text is Meta's accessibility layer, and the AI caption
 * drafts with the tenant's own enabled model into the textarea — never
 * straight to the feed. Turning comments off, tagging people and hiding
 * like counts on images are NOT in the publishing API, so instead of dead
 * toggles the composer says so.
 */

const MAX_IMAGES = 10; // Instagram's carousel cap — also the API's limit.
const CAPTION_MAX = 2200;

const FIELD =
  "rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

type Entry = { key: string; url: string; file?: File };

function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 disabled:opacity-50"
    >
      <span
        className={`relative inline-block h-6 w-10 shrink-0 rounded-full ${
          checked
            ? "bg-[var(--ui-ink)]"
            : "border border-[var(--ui-line-strong)] bg-[var(--ui-sunken)]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full transition-transform ${
            checked
              ? "translate-x-[18px] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
              : "translate-x-0.5 border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
          }`}
        />
      </span>
      <span className={`text-left text-[13px] font-semibold ${INK}`}>{label}</span>
    </button>
  );
}

/* A tiny live preview of the post, laid out like the feed shows it. */
function PostPreview({
  first,
  username,
  caption,
  ratio,
  locationName,
}: {
  first: Entry | null;
  username: string | null;
  caption: string;
  ratio: CropRatio;
  locationName: string | null;
}) {
  const aspect = ratio.aspect ?? 1;
  return (
    <div className="w-full max-w-[232px] overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)]">
      <div className="flex items-center gap-2 px-3 py-2">
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
        >
          <PlatformMark platform="instagram" size={14} />
        </span>
        <span className={`text-[13px] font-bold ${INK}`}>{username || "your account"}</span>
      </div>
      <div
        className="w-full bg-black"
        style={{ aspectRatio: String(aspect) }}
      >
        {first ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={first.url}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : null}
      </div>
      <div className="px-3 py-2">
        <p className={`text-[13px] leading-snug ${INK}`}>
          <span className="mr-1.5 font-bold">{username || "your account"}</span>
          {caption || "Your caption appears here."}
        </p>
        {locationName && (
          <p className={`mt-1 text-[12px] font-semibold ${INK2}`}>📍 {locationName}</p>
        )}
      </div>
    </div>
  );
}

export default function PostComposer({
  igId,
  accountUsername,
  onPublished,
}: {
  igId: string;
  accountUsername?: string | null;
  onPublished: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [pending, setPending] = useState<File[]>([]);
  const [ratio, setRatio] = useState<CropRatio>(CROP_RATIOS[0]);
  const [urlDraft, setUrlDraft] = useState("");
  const [caption, setCaption] = useState("");
  const [altText, setAltText] = useState("");
  const [toStory, setToStory] = useState(false);
  const [toFacebook, setToFacebook] = useState(false);
  const [location, setLocation] = useState<InstagramLocation | null>(null);
  const [locQuery, setLocQuery] = useState("");
  const [locResults, setLocResults] = useState<InstagramLocation[] | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [publishedNote, setPublishedNote] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ total: number; used: number } | null>(null);
  const nextKey = useRef(0);
  const cropBusyRef = useRef(false);

  // The quota line is informational — a refused read (older scope set)
  // degrades to zeros server-side and we simply don't render it.
  const loadQuota = useCallback(() => {
    fetchInstagramPublishingLimit(igId).then(
      (q) => {
        if (q.quota_total > 0) setQuota({ total: q.quota_total, used: q.quota_usage });
      },
      () => {},
    );
  }, [igId]);

  const toggle = () => {
    setOpen((v) => {
      if (!v) loadQuota();
      return !v;
    });
  };

  const uploadBlob = async (blob: Blob, baseName: string): Promise<string> => {
    // The API checks content against the filename (polyglot guard), so the
    // extension must describe the ACTUAL bytes — "Original" passes the file
    // through untouched (a PNG stays PNG), while crops re-encode to JPEG.
    const ext =
      blob.type === "image/png" ? ".png"
      : blob.type === "image/webp" ? ".webp"
      : blob.type === "image/gif" ? ".gif"
      : ".jpg";
    const name = baseName.replace(/\.[^.]+$/, "") + ext;
    const form = new FormData();
    form.append("file", new File([blob], name, { type: blob.type || "image/jpeg" }));
    let result: Awaited<ReturnType<typeof apiFetch>>;
    try {
      result = await apiFetch("/api/v1/storage/upload", {
        method: "POST",
        body: form,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      // A dead tunnel surfaces as "Failed to fetch" or a raw Cloudflare
      // HTML error page — neither tells the person publishing what to do.
      const unreachable =
        /failed to fetch|networkerror|load failed/i.test(msg) || /^\s*</.test(msg);
      let friendly = msg;
      try {
        const parsed = JSON.parse(msg) as { detail?: unknown };
        if (typeof parsed?.detail === "string") friendly = parsed.detail;
      } catch {
        /* not JSON — show the message as-is */
      }
      throw new Error(
        unreachable
          ? "The server was unreachable for a moment — your image is still here, press Done to try again."
          : friendly || "Upload failed.",
      );
    }
    if (typeof result?.url !== "string" || !result.url.startsWith("https://")) {
      throw new Error(
        "Instagram fetches images from a public HTTPS url, and this server's storage is not public. Host the image somewhere public and paste its link below.",
      );
    }
    return result.url;
  };

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const room = MAX_IMAGES - entries.length - pending.length;
    const picked = Array.from(files).slice(0, Math.max(0, room));
    if (picked.length === 0) {
      setError(`Up to ${MAX_IMAGES} images per post.`);
      return;
    }
    setError(null);
    setPending((prev) => [...prev, ...picked]);
  };

  const finishCrop = async (blob: Blob) => {
    const file = pending[0];
    if (!file || cropBusyRef.current) return;
    cropBusyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const url = await uploadBlob(blob, file.name);
      nextKey.current += 1;
      setEntries((prev) =>
        [...prev, { key: `e${nextKey.current}`, url, file }].slice(0, MAX_IMAGES),
      );
      setPending((prev) => prev.slice(1));
    } catch (e) {
      // Keep the file queued — the crop editor stays open so Done retries.
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      cropBusyRef.current = false;
      setBusy(false);
    }
  };

  const addHostedUrl = () => {
    const value = urlDraft.trim();
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch {
      setError("Enter a valid image URL.");
      return;
    }
    if (parsed.protocol !== "https:") {
      setError("Instagram fetches images itself — the link must be public HTTPS.");
      return;
    }
    setError(null);
    nextKey.current += 1;
    setEntries((prev) =>
      (prev.length >= MAX_IMAGES ? prev : [...prev, { key: `e${nextKey.current}`, url: value }]),
    );
    setUrlDraft("");
  };

  // Debounced place search while no place is chosen; the dropdown shows
  // results only for a live query — derived in render, never synced here.
  useEffect(() => {
    const q = locQuery.trim();
    if (location || q.length < 2) return;
    let cancelled = false;
    const t = setTimeout(() => {
      fetchInstagramLocations(igId, q).then(
        (r) => {
          if (!cancelled) setLocResults(r.locations);
        },
        () => {
          if (!cancelled) setLocResults([]);
        },
      );
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [locQuery, location, igId]);

  const showResults =
    !location && locQuery.trim().length >= 2 ? locResults : null;

  const generateCaption = async () => {
    if (aiBusy) return;
    setAiBusy(true);
    setError(null);
    try {
      const out = await suggestInstagramCaption(igId, "", caption);
      setCaption(out.caption.slice(0, CAPTION_MAX));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Caption generation failed.");
    } finally {
      setAiBusy(false);
    }
  };

  const publish = async () => {
    if (entries.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: Parameters<typeof publishToInstagram>[1] = {
        image_urls: entries.map((e) => e.url),
        caption: caption.trim(),
      };
      if (location) body.location_id = location.id;
      if (toFacebook) body.share_to_facebook = true;
      if (altText.trim()) body.alt_text = altText.trim();

      if (toStory) {
        const firstFile = entries[0]?.file;
        if (!firstFile) {
          throw new Error("Stories need an uploaded image we can crop to 9:16 — pasted links can't be cropped here.");
        }
        const storyBlob = await centerCropBlob(firstFile, STORY_RATIO);
        body.story_image_urls = [await uploadBlob(storyBlob, "story-916")];
      }

      const out = await publishToInstagram(igId, body);
      const failed = out.story_media_ids.filter((s) => s.startsWith("failed:"));
      const storiesOk = out.story_media_ids.length - failed.length;
      setPublishedNote(
        `Published — it appears in the grid below.` +
          (storiesOk ? ` Story shared too.` : "") +
          (failed.length ? ` Story refused: ${failed[0].slice(8, 130)}` : ""),
      );
      setEntries([]);
      setCaption("");
      setAltText("");
      setToStory(false);
      setLocation(null);
      setLocQuery("");
      setLocResults(null);
      onPublished();
      loadQuota();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Instagram refused the post.");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={toggle}
          className="ui-btn rounded-lg bg-[var(--ui-ink)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-on-ink)]"
        >
          New post
        </button>
        {quota && (
          <span className={`text-[12px] ${INK2}`}>
            {quota.used} of {quota.total} posts used in the next 24 hours
          </span>
        )}
      </div>
    );
  }

  const cropFile = pending[0] ?? null;
  const storyAvailable = Boolean(entries[0]?.file);

  return (
    <section className="rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className={`text-[13px] font-semibold ${INK}`}>New post</h4>
        {quota && (
          <span className={`text-[12px] ${INK2}`}>
            {quota.used} of {quota.total} posts used in the next 24 hours
          </span>
        )}
      </div>

      {cropFile && (
        <div className="mt-3">
          <CropEditor
            key={`${cropFile.name}:${cropFile.size}:${ratio.key}`}
            file={cropFile}
            ratio={ratio}
            onRatio={setRatio}
            index={0}
            total={pending.length}
            working={busy}
            onCancel={() => setPending((prev) => prev.slice(1))}
            onDone={(blob) => void finishCrop(blob)}
          />
        </div>
      )}

      {!cropFile && (
        <>
          {publishedNote && (
            <p className="mt-3 rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] font-semibold text-[var(--ui-ink)]">
              {publishedNote}
            </p>
          )}

          <div className="mt-3 grid gap-4 sm:grid-cols-[232px_minmax(0,1fr)]">
            <PostPreview
              first={entries[0] ?? null}
              username={accountUsername ?? null}
              caption={caption.trim()}
              ratio={ratio}
              locationName={location?.name ?? null}
            />

            <div className="min-w-0 space-y-3">
              <label className="flex cursor-pointer items-center justify-center rounded-[12px] border border-dashed border-[var(--ui-line)] bg-[var(--ui-sunken)] px-4 py-5 text-[12px] font-semibold text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]">
                {busy ? "Working…" : "Add images (up to 10 — they become a carousel)"}
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  className="sr-only"
                  disabled={busy}
                  onChange={(e) => {
                    handleFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>

              {entries.length > 0 && (
                <ul className="flex flex-wrap gap-2">
                  {entries.map((e, i) => (
                    <li key={e.key} className="relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={e.url}
                        alt={`Post image ${i + 1}`}
                        className="h-16 w-16 rounded-[8px] border border-[var(--ui-line)] object-cover"
                      />
                      {i === 0 && (
                        <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 rounded-full bg-[var(--ui-ink)] px-1.5 text-[9px] font-bold text-[var(--ui-on-ink)]">
                          1st
                        </span>
                      )}
                      <button
                        type="button"
                        aria-label={`Remove image ${i + 1}`}
                        onClick={() =>
                          setEntries((prev) => prev.filter((x) => x.key !== e.key))
                        }
                        className="absolute -right-1.5 -top-1.5 h-5 w-5 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[11px] font-bold text-[var(--ui-ink)]"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex items-center gap-2">
                <input
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addHostedUrl();
                    }
                  }}
                  placeholder="…or paste a public HTTPS image link"
                  aria-label="Public image URL"
                  className={`${FIELD} min-w-0 flex-1`}
                />
                <button
                  type="button"
                  onClick={addHostedUrl}
                  disabled={busy || !urlDraft.trim()}
                  className="rounded-[12px] border border-[var(--ui-line)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)] disabled:opacity-50"
                >
                  Add
                </button>
              </div>

              {/* Feed shape is decided in the crop step; the preview above
                  mirrors it. Meta crops carousel children to the FIRST
                  image, so the 1st badge is the honest marker. */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={`text-[12px] font-semibold ${INK2}`}>Shape</span>
                {CROP_RATIOS.map((r) => (
                  <button
                    key={r.key}
                    type="button"
                    onClick={() => setRatio(r)}
                    className={`rounded-full border px-3 py-1 text-[12px] font-semibold ${
                      ratio.key === r.key
                        ? "border-[var(--ui-ink)] bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                        : `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK} hover:bg-[var(--ui-line)]`
                    }`}
                  >
                    {r.label} <span className="opacity-60">{r.hint}</span>
                  </button>
                ))}
              </div>

              <div>
                <div className="flex items-center justify-between gap-2">
                  <textarea
                    value={caption}
                    onChange={(e) => setCaption(e.target.value)}
                    rows={3}
                    maxLength={CAPTION_MAX}
                    aria-label="Caption"
                    placeholder="Caption…"
                    className={`${FIELD} w-full resize-y`}
                  />
                </div>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => void generateCaption()}
                    disabled={aiBusy}
                    className="flex items-center gap-1.5 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] hover:bg-[var(--ui-line)] disabled:opacity-50"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src="/Sayvors_Icon.png"
                      alt=""
                      width={16}
                      height={16}
                      className="rounded-[4px]"
                    />
                    {aiBusy ? "Writing…" : "Generate AI Caption"}
                  </button>
                  <span className={`text-[11px] tabular-nums ${INK2}`}>
                    {caption.length}/{CAPTION_MAX}
                  </span>
                </div>
              </div>

              <div className="grid gap-2.5 sm:grid-cols-2">
                <Switch
                  checked={toStory}
                  onChange={setToStory}
                  disabled={!storyAvailable}
                  label="Also share to story"
                />
                <Switch
                  checked={toFacebook}
                  onChange={setToFacebook}
                  label="Share to Facebook"
                />
              </div>
              {toStory && !storyAvailable && (
                <p className={`text-[12px] ${INK2}`}>
                  Stories must be 9:16 — upload the image here (not a pasted
                  link) and we crop it automatically.
                </p>
              )}
              {entries.length === 0 && (
                <p className={`text-[12px] ${INK2}`}>
                  Add at least one image above — Publish and the story toggle
                  unlock once an image is in.
                </p>
              )}

              <div>
                {location ? (
                  <span className="inline-flex items-center gap-2 rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)]">
                    📍 {location.name}
                    <button
                      type="button"
                      aria-label="Remove location"
                      onClick={() => {
                        setLocation(null);
                        setLocQuery("");
                      }}
                      className="font-bold"
                    >
                      ×
                    </button>
                  </span>
                ) : (
                  <div className="relative">
                    <input
                      value={locQuery}
                      onChange={(e) => setLocQuery(e.target.value)}
                      placeholder="Add location…"
                      aria-label="Search locations"
                      className={`${FIELD} w-full`}
                    />
                    {showResults !== null && (
                      <ul className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] shadow-[0_4px_12px_rgba(0,0,0,0.12)]">
                        {showResults.length === 0 ? (
                          <li className={`px-3 py-2 text-[12px] ${INK2}`}>
                            {locQuery.trim().length >= 2 && "No places found — location tagging needs a Facebook-linked account."}
                          </li>
                        ) : (
                          showResults.map((p) => (
                            <li key={p.id}>
                              <button
                                type="button"
                                onClick={() => {
                                  setLocation(p);
                                  setLocResults(null);
                                }}
                                className={`w-full px-3 py-2 text-left text-[13px] ${INK} hover:bg-[var(--ui-sunken)]`}
                              >
                                {p.name}
                              </button>
                            </li>
                          ))
                        )}
                      </ul>
                    )}
                  </div>
                )}
              </div>

              <input
                value={altText}
                onChange={(e) => setAltText(e.target.value)}
                maxLength={1000}
                placeholder="Alt text — describe the image for visually impaired people"
                aria-label="Alt text"
                className={`${FIELD} w-full`}
              />

              {error && (
                <p role="alert" className="text-[12px] font-semibold text-red-600 dark:text-red-400">
                  {error}
                </p>
              )}

              <p className={`text-[11px] leading-relaxed ${INK2}`}>
                Instagram&apos;s API doesn&apos;t let apps turn comments off,
                tag people or collaborators, or hide like counts on image
                posts — manage those in the Instagram app after publishing.
              </p>

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={toggle}
                  disabled={busy}
                  className="rounded-[12px] border border-[var(--ui-line)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)] disabled:opacity-50"
                >
                  Close
                </button>
                <button
                  type="button"
                  onClick={() => void publish()}
                  disabled={busy || entries.length === 0}
                  className="rounded-[12px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)] disabled:opacity-50"
                >
                  {busy ? "Publishing…" : "Publish"}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
