"use client";

import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import {
  deleteInstagramComment,
  fetchInstagramComments,
  fetchInstagramPosts,
  replyToInstagramComment,
  setInstagramCommentHidden,
  type InstagramStoredComment,
} from "@/lib/api-meta";
import { useInboxRealtime } from "@/lib/use-inbox-realtime";
import { Avatar, INK, INK2, timeAgo } from "./ui";

/*
 * The comment inbox: everything anyone has said on this account's posts,
 * stored server-side the moment it arrives — with replies, hide and
 * delete done right here. This is Sayvors' core loop for Instagram:
 * people comment on OUR videos, we answer from one place.
 *
 * Rows arrive over the realtime socket too, so a fresh comment appears
 * without touching refresh. A deleted row keeps its place in the thread
 * with a "deleted" marker — history, not a hole. Hidden is Meta's own
 * soft-deletion: invisible in the public feed, visible to its author.
 */

function Chip({ children }: { children: string }) {
  return (
    <span className="rounded-full border border-[var(--ui-line)] px-2 py-0.5 text-[11px] font-semibold text-[var(--ui-ink-2)]">
      {children}
    </span>
  );
}

function MediaThumb({ mediaId, thumbs }: { mediaId: string | null; thumbs: Record<string, string | null> }) {
  const url = mediaId ? thumbs[mediaId] : undefined;
  if (!mediaId) return null;
  return (
    <span
      title="On this post"
      className="relative block h-8 w-8 shrink-0 overflow-hidden rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
    >
      {url ? (
        <Image src={url} alt="" fill sizes="32px" unoptimized className="object-cover" />
      ) : null}
    </span>
  );
}

function ReplyBox({
  igId,
  commentId,
  onSent,
}: {
  igId: string;
  commentId: string;
  onSent: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const message = draft.trim();
    if (!message || busy) return;
    setBusy(true);
    setError(null);
    try {
      await replyToInstagramComment(igId, commentId, message);
      setDraft("");
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not post the reply.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2">
      <div className="flex items-start gap-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={2}
          maxLength={2200}
          aria-label="Write a reply"
          placeholder="Reply publicly…"
          className="min-h-[38px] flex-1 resize-y rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        />
        <button
          type="button"
          onClick={() => void send()}
          disabled={busy || !draft.trim()}
          className="rounded-[12px] bg-[var(--ui-ink)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)] disabled:opacity-50"
        >
          {busy ? "Sending…" : "Reply"}
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-1 text-[12px] font-semibold text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

function CommentRow({
  c,
  igId,
  accountUsername,
  thumbs,
  onChanged,
  child,
}: {
  c: InstagramStoredComment;
  igId: string;
  accountUsername: string | null;
  thumbs: Record<string, string | null>;
  onChanged: () => void;
  child?: boolean;
}) {
  const [replying, setReplying] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const inbound = c.direction === "inbound";
  const who = inbound
    ? c.author_name
      ? `@${c.author_name}`
      : "Instagram user"
    : accountUsername
      ? `@${accountUsername}`
      : "You";

  const toggleHidden = async () => {
    setActionError(null);
    try {
      await setInstagramCommentHidden(igId, c.comment_id!, !c.hidden);
      onChanged();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not update the comment.");
    }
  };

  const remove = async () => {
    if (!confirmDel) {
      setConfirmDel(true);
      return;
    }
    setActionError(null);
    try {
      await deleteInstagramComment(igId, c.comment_id!);
      onChanged();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not delete the comment.");
      setConfirmDel(false);
    }
  };

  return (
    <li className={child ? "border-l-2 border-[var(--ui-line)] py-2 pl-4" : "border-b border-[var(--ui-line)] py-3 last:border-0"}>
      <div className="flex items-start gap-3">
        <Avatar name={inbound ? who : accountUsername || "You"} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] leading-snug">
            <span className={`font-semibold ${INK}`}>{who}</span>{" "}
            <span className={c.deleted_at ? `line-through opacity-60 ${INK}` : INK}>
              {c.content}
            </span>
          </p>
          <p className={`mt-1 flex flex-wrap items-center gap-2 text-[12px] ${INK2}`}>
            <span>{timeAgo(c.platform_timestamp ?? c.created_at) || "just now"}</span>
            {c.hidden && <Chip>Hidden</Chip>}
            {c.deleted_at && <Chip>Deleted</Chip>}
            {c.status === "failed" && <Chip>Failed</Chip>}
            {!inbound && c.status === "sent" && <Chip>You</Chip>}
          </p>
          {c.status === "failed" && c.error && (
            <p className="mt-1 text-[12px] text-red-600 dark:text-red-400">
              Instagram refused this reply — try again.
            </p>
          )}
          {actionError && (
            <p role="alert" className="mt-1 text-[12px] font-semibold text-red-600 dark:text-red-400">
              {actionError}
            </p>
          )}

          {inbound && c.comment_id && !c.deleted_at && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[12px] font-semibold">
              <button
                type="button"
                onClick={() => setReplying((v) => !v)}
                className={`${INK} underline-offset-2 hover:underline`}
              >
                {replying ? "Cancel" : "Reply"}
              </button>
              <button
                type="button"
                onClick={() => void toggleHidden()}
                className={`${INK2} underline-offset-2 hover:underline`}
              >
                {c.hidden ? "Unhide" : "Hide"}
              </button>
              <button
                type="button"
                onClick={() => void remove()}
                className="text-red-600 underline-offset-2 hover:underline dark:text-red-400"
              >
                {confirmDel ? "Really delete?" : "Delete"}
              </button>
            </div>
          )}
          {replying && c.comment_id && (
            <ReplyBox igId={igId} commentId={c.comment_id} onSent={onChanged} />
          )}
        </div>
        <MediaThumb mediaId={c.media_id} thumbs={thumbs} />
      </div>
    </li>
  );
}

export default function CommentsTab({
  igId,
  accountUsername,
}: {
  igId: string;
  accountUsername?: string | null;
}) {
  const [comments, setComments] = useState<InstagramStoredComment[] | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  // Event handlers (retry, realtime socket) own the synchronous reset; the
  // effect's promise callbacks own everything after the await.
  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    setReload((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchInstagramComments(igId),
      fetchInstagramPosts(igId).catch(() => null),
    ]).then(
      ([inbox, posts]) => {
        if (cancelled) return;
        setComments(inbox.comments);
        const map: Record<string, string | null> = {};
        for (const p of posts?.posts ?? []) {
          if (p.id) map[p.id] = p.thumbnail_url ?? p.media_url ?? null;
        }
        setThumbs(map);
        setLoading(false);
      },
      (e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load comments.");
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [igId, reload]);

  useInboxRealtime((e) => {
    if (e.platform && e.platform !== "instagram") return;
    if (
      e.type === "comment" ||
      e.type === "comment_updated" ||
      e.type === "comment_deleted"
    ) {
      refresh();
    }
  });

  if (loading && comments === null) {
    return (
      <div className="space-y-3" aria-hidden>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-14 animate-pulse rounded-[12px] bg-[var(--ui-sunken)]" />
        ))}
      </div>
    );
  }

  if (error && comments === null) {
    return (
      <div role="alert" className="rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4">
        <p className={`text-[13px] font-bold ${INK}`}>{error}</p>
        <button
          type="button"
          onClick={refresh}
          className="ui-btn mt-3 rounded-lg bg-[var(--ui-surface)] px-4 py-2.5 text-[12px] font-semibold text-[var(--ui-ink)]"
        >
          Try again
        </button>
      </div>
    );
  }

  const rows = comments ?? [];
  if (rows.length === 0) {
    return (
      <p className={`text-[13px] ${INK2}`}>
        No comments yet. When someone comments on your posts, they show up here —
        and you reply right from Sayvors.
      </p>
    );
  }

  // Newest conversation first; a thread reads oldest → newest, replies
  // indented under the comment they answer.
  const tops = rows
    .filter((c) => !c.parent_comment_id)
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const byParent = new Map<string, InstagramStoredComment[]>();
  for (const c of rows) {
    if (!c.parent_comment_id) continue;
    const list = byParent.get(c.parent_comment_id) ?? [];
    list.push(c);
    byParent.set(c.parent_comment_id, list);
  }

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-2 pb-3">
        <h3 className={`text-[15px] font-semibold ${INK}`}>Comments</h3>
        <span className={`text-[12px] ${INK2}`}>
          {rows.length} stored · live
        </span>
      </div>
      <ul>
        {tops.map((c) => (
          <li key={c.id}>
            <ul>
              <CommentRow
                c={c}
                igId={igId}
                accountUsername={accountUsername ?? null}
                thumbs={thumbs}
                onChanged={refresh}
              />
              {(byParent.get(c.comment_id ?? "") ?? []).map((r) => (
                <CommentRow
                  key={r.id}
                  c={r}
                  igId={igId}
                  accountUsername={accountUsername ?? null}
                  thumbs={thumbs}
                  onChanged={refresh}
                  child
                />
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}
