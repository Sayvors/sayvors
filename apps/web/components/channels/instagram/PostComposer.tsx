"use client";

import { useCallback, useState } from "react";
import {
  fetchInstagramPublishingLimit,
  publishToInstagram,
} from "@/lib/api-meta";
import { apiFetch } from "@/lib/api-rag";
import { INK, INK2 } from "./ui";

/*
 * Publish images to the tenant's OWN Instagram feed, from Sayvors.
 *
 * Meta fetches the images itself, so every url must be publicly reachable
 * over HTTPS — uploads go through Sayvors storage, which hands back exactly
 * such a url (local HTTP storage is refused here with a plain-language
 * error). One image is a single post; several become a carousel. The
 * caption rides the post, 2200 characters, Instagram's own cap.
 *
 * After a successful publish the grid below refreshes; the new post also
 * lands in the comments inbox automatically, since it is now "our media".
 */

const MAX_IMAGES = 10; // Instagram's carousel cap — also the API's limit.
const CAPTION_MAX = 2200;

const FIELD =
  "rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

export default function PostComposer({
  igId,
  onPublished,
}: {
  igId: string;
  onPublished: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [images, setImages] = useState<string[]>([]);
  const [urlDraft, setUrlDraft] = useState("");
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [publishedId, setPublishedId] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ total: number; used: number } | null>(null);

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

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const room = MAX_IMAGES - images.length;
    const picked = Array.from(files).slice(0, Math.max(0, room));
    if (picked.length === 0) {
      setError(`Up to ${MAX_IMAGES} images per post.`);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const uploaded: string[] = [];
      for (const file of picked) {
        const form = new FormData();
        form.append("file", file);
        const result = await apiFetch("/api/v1/storage/upload", {
          method: "POST",
          body: form,
        });
        if (typeof result?.url !== "string" || !result.url.startsWith("https://")) {
          throw new Error(
            "Instagram fetches images from a public HTTPS url, and this server's storage is not public. Host the image somewhere public and paste its link below.",
          );
        }
        uploaded.push(result.url);
      }
      setImages((prev) => [...prev, ...uploaded].slice(0, MAX_IMAGES));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
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
    setImages((prev) => (prev.length >= MAX_IMAGES ? prev : [...prev, value]));
    setUrlDraft("");
  };

  const publish = async () => {
    if (images.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const out = await publishToInstagram(igId, images, caption.trim());
      setPublishedId(out.media_id);
      setImages([]);
      setCaption("");
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

      {publishedId && (
        <p className="mt-3 rounded-[8px] bg-[var(--ui-sunken)] p-3 text-[12px] font-semibold text-[var(--ui-ink)]">
          Published — it appears in the grid below. ({publishedId})
        </p>
      )}

      <label className="mt-3 flex cursor-pointer items-center justify-center rounded-[12px] border border-dashed border-[var(--ui-line)] bg-[var(--ui-sunken)] px-4 py-6 text-[12px] font-semibold text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]">
        {busy ? "Working…" : "Add images (up to 10 — they become a carousel)"}
        <input
          type="file"
          accept="image/jpeg,image/png"
          multiple
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            void handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </label>

      {images.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {images.map((src, i) => (
            <li key={src} className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={src}
                alt={`Post image ${i + 1}`}
                className="h-16 w-16 rounded-[8px] border border-[var(--ui-line)] object-cover"
              />
              <button
                type="button"
                aria-label={`Remove image ${i + 1}`}
                onClick={() => setImages((prev) => prev.filter((_, j) => j !== i))}
                className="absolute -right-1.5 -top-1.5 h-5 w-5 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[11px] font-bold text-[var(--ui-ink)]"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-2">
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

      <textarea
        value={caption}
        onChange={(e) => setCaption(e.target.value)}
        rows={3}
        maxLength={CAPTION_MAX}
        aria-label="Caption"
        placeholder="Caption…"
        className={`${FIELD} mt-3 w-full resize-y`}
      />
      <p className={`mt-1 text-right text-[11px] tabular-nums ${INK2}`}>
        {caption.length}/{CAPTION_MAX}
      </p>

      {error && (
        <p role="alert" className="mt-2 text-[12px] font-semibold text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mt-3 flex items-center justify-end gap-2">
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
          disabled={busy || images.length === 0}
          className="rounded-[12px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)] disabled:opacity-50"
        >
          {busy ? "Publishing…" : "Publish"}
        </button>
      </div>
    </section>
  );
}
