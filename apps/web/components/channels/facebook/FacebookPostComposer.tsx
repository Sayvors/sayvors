"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { publishToFacebook } from "@/lib/api-meta";
import { INK2 } from "../instagram/ui";
import { Switch } from "../ui";

/*
 * Composer for the tenant's OWN Page feed: text, link, 1–10 photos, or any
 * of those scheduled for later. No crop step on purpose — Facebook scales
 * images itself, so the file goes up as the person picked it. Nothing
 * auto-posts: this button is the only way a post leaves Sayvors.
 */

const MAX_IMAGES = 10;
const MESSAGE_MAX = 5000;

const FIELD =
  "rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

type Entry = {
  key: string;
  // Set once the file is on our storage — the url Meta will fetch.
  url?: string;
  file?: File;
  preview?: string;
  busy?: boolean;
  error?: string;
};

const uploadBlob = async (blob: Blob, baseName: string): Promise<string> => {
  // The API checks content against the filename (polyglot guard), so the
  // extension must describe the ACTUAL bytes.
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
        ? "The server was unreachable for a moment — your image is still here, press Retry."
        : friendly || "Upload failed.",
    );
  }
  if (typeof result?.url !== "string" || !result.url.startsWith("https://")) {
    throw new Error(
      "Facebook fetches images from a public HTTPS url, and this server's storage is not public. Host the image somewhere public and paste its link below.",
    );
  }
  return result.url;
};

export default function FacebookPostComposer({
  pageId,
  onPublished,
}: {
  pageId: string;
  onPublished: () => void;
}) {
  const [message, setMessage] = useState("");
  const [link, setLink] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [pasteUrl, setPasteUrl] = useState("");
  const [scheduleOn, setScheduleOn] = useState(false);
  const [scheduleAt, setScheduleAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const patchEntry = (key: string, patch: Partial<Entry>) => {
    setEntries((list) => list.map((e) => (e.key === key ? { ...e, ...patch } : e)));
  };

  const uploadEntry = async (key: string, file: File) => {
    patchEntry(key, { busy: true, error: undefined });
    try {
      const url = await uploadBlob(file, file.name || "photo");
      patchEntry(key, { url, busy: false });
    } catch (e) {
      patchEntry(key, {
        busy: false,
        error: e instanceof Error ? e.message : "Upload failed.",
      });
    }
  };

  const handleFiles = (files: FileList | null) => {
    setError(null);
    setDone(null);
    if (!files) return;
    const room = MAX_IMAGES - entries.length;
    const picked = Array.from(files).slice(0, Math.max(0, room));
    if (picked.length === 0) return;
    for (const file of picked) {
      const key = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const entry: Entry = { key, file, preview: URL.createObjectURL(file) };
      setEntries((list) => [...list, entry]);
      void uploadEntry(key, file);
    }
  };

  const addPastedUrl = () => {
    const url = pasteUrl.trim();
    if (!url) return;
    setError(null);
    setDone(null);
    if (entries.length >= MAX_IMAGES) {
      setError(`Facebook takes at most ${MAX_IMAGES} photos per post.`);
      return;
    }
    setEntries((list) => [...list, { key: `url-${Date.now()}`, url }]);
    setPasteUrl("");
  };

  const removeEntry = (key: string) => {
    setEntries((list) => {
      const target = list.find((e) => e.key === key);
      if (target?.preview) URL.revokeObjectURL(target.preview);
      return list.filter((e) => e.key !== key);
    });
  };

  const images = entries.filter((e) => e.url).map((e) => e.url!);
  const pending = entries.filter((e) => e.busy).length;
  const failed = entries.filter((e) => e.error).length;

  const publish = async () => {
    if (busy) return;
    setError(null);
    setDone(null);
    const trimmedLink = link.trim();
    if (!message.trim() && !trimmedLink && images.length === 0) {
      setError("Write a message, add a link, or attach a photo first.");
      return;
    }
    if (trimmedLink && images.length > 0) {
      setError("Facebook takes either a link or photos per post — not both.");
      return;
    }
    if (pending > 0) {
      setError("Hold on — the photos are still uploading.");
      return;
    }
    if (failed > 0) {
      setError("Retry or remove the photo that failed to upload.");
      return;
    }
    let scheduleIso: string | undefined;
    if (scheduleOn) {
      if (!scheduleAt) {
        setError("Pick a date and time to schedule for.");
        return;
      }
      const when = new Date(scheduleAt);
      const mins = (when.getTime() - Date.now()) / 60000;
      if (Number.isNaN(mins) || mins < 10) {
        setError("Scheduled time must be at least 10 minutes from now.");
        return;
      }
      scheduleIso = when.toISOString();
    }
    setBusy(true);
    try {
      const out = await publishToFacebook(pageId, {
        message: message.trim() || undefined,
        link: trimmedLink || undefined,
        image_urls: images.length > 0 ? images : undefined,
        schedule_at: scheduleIso,
      });
      setMessage("");
      setLink("");
      for (const e of entries) if (e.preview) URL.revokeObjectURL(e.preview);
      setEntries([]);
      setScheduleOn(false);
      setScheduleAt("");
      setDone(
        out.scheduled
          ? "Scheduled — Facebook will publish it at the time you picked."
          : "Published to your Page."
      );
      onPublished();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not publish.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-4">
      <textarea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        rows={3}
        maxLength={MESSAGE_MAX}
        aria-label="Post message"
        placeholder="What's new with your business?"
        className={`${FIELD} w-full resize-y`}
      />
      <p className={`mt-1 text-right text-[11px] ${INK2}`}>
        {message.length}/{MESSAGE_MAX}
      </p>

      <div className="mt-3">
        <label className={`text-[12px] font-semibold ${INK2}`} htmlFor="fb-link">
          Link (optional)
        </label>
        <input
          id="fb-link"
          type="url"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder="https://…"
          disabled={entries.some((e) => e.url)}
          className={`${FIELD} mt-1 w-full disabled:opacity-50`}
        />
      </div>

      <div className="mt-4">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={entries.length >= MAX_IMAGES}
            className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)] disabled:opacity-50"
          >
            Add photos ({entries.length}/{MAX_IMAGES})
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            type="url"
            value={pasteUrl}
            onChange={(e) => setPasteUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addPastedUrl();
              }
            }}
            placeholder="…or paste an image url"
            aria-label="Paste an image url"
            className={`${FIELD} min-w-[12rem] flex-1`}
          />
          <button
            type="button"
            onClick={addPastedUrl}
            disabled={!pasteUrl.trim()}
            className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)] disabled:opacity-50"
          >
            Add
          </button>
        </div>

        {entries.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2">
            {entries.map((e) => (
              <li key={e.key} className="relative">
                <span className="block h-20 w-20 overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)]">
                  {e.preview ? (
                    <Image
                      src={e.preview}
                      alt=""
                      width={80}
                      height={80}
                      unoptimized
                      className={`h-20 w-20 object-cover ${e.error ? "opacity-40" : ""}`}
                    />
                  ) : e.url ? (
                    <Image
                      src={e.url}
                      alt=""
                      width={80}
                      height={80}
                      unoptimized
                      className="h-20 w-20 object-cover"
                    />
                  ) : null}
                </span>
                {e.busy && (
                  <span className="absolute inset-0 flex items-center justify-center rounded-[12px] bg-[var(--ui-surface)]/80 text-[11px] font-bold text-[var(--ui-ink)]">
                    Uploading…
                  </span>
                )}
                {e.error && (
                  <button
                    type="button"
                    onClick={() => e.file && void uploadEntry(e.key, e.file)}
                    className="absolute inset-x-1 bottom-1 rounded-[8px] bg-[var(--ui-ink)] px-1 py-0.5 text-[10px] font-bold text-[var(--ui-on-ink)]"
                  >
                    Retry
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => removeEntry(e.key)}
                  aria-label="Remove photo"
                  className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-[var(--ui-ink)] text-[11px] font-bold text-[var(--ui-on-ink)]"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {entries.some((e) => e.error) && (
          <p role="alert" className="mt-2 text-[12px] font-semibold text-red-600 dark:text-red-400">
            {entries.find((e) => e.error)?.error}
          </p>
        )}
      </div>

      <div className="mt-4 border-t border-[var(--ui-line)] pt-3">
        <Switch
          checked={scheduleOn}
          onChange={(v) => {
            setScheduleOn(v);
            setDone(null);
          }}
          label="Schedule for later"
        />
        {scheduleOn && (
          <input
            type="datetime-local"
            value={scheduleAt}
            onChange={(e) => setScheduleAt(e.target.value)}
            aria-label="Publish at"
            className={`${FIELD} mt-2 w-full sm:w-64`}
          />
        )}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-[12px] font-semibold text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {done && (
        <p role="status" className="mt-3 text-[12px] font-semibold text-[var(--ui-ink)]">
          {done}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void publish()}
          disabled={busy || pending > 0}
          className="rounded-[12px] bg-[var(--ui-ink)] px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] disabled:opacity-50"
        >
          {busy
            ? "Publishing…"
            : scheduleOn
              ? "Schedule post"
              : "Publish to Page"}
        </button>
        <span className={`text-[11px] ${INK2}`}>
          Published posts can&apos;t be edited or boosted from Sayvors — manage those on Facebook.
        </span>
      </div>
    </div>
  );
}
