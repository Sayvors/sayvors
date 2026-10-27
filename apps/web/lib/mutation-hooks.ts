"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approveReply, editReply, type ReviewReplyDTO } from "@/lib/api-analytics";
import { updateReviewIssue, type ReviewIssue, type ReviewIssuePatch } from "@/lib/api-review-issues";
import { apiFetch } from "@/lib/api-rag";

/**
 * Reusable mutation hooks with cache invalidation.
 *
 * Each hook wraps one admin/owner action and invalidates the TanStack Query
 * keys it affects, so callers never have to remember to refetch. Mutations
 * surface errors via the returned `error`/`isError` (and an optional
 * `onError` callback) — they never throw into the render path.
 *
 * Adoption is incremental: pages can keep their existing hand-rolled flows
 * and swap in these hooks one call site at a time.
 */

/** Approve a drafted reply and publish it to Google. */
export function useApproveReply() {
  const queryClient = useQueryClient();
  return useMutation<ReviewReplyDTO, Error, { channelId: string; replyId: string }>({
    mutationFn: ({ channelId, replyId }) => approveReply(channelId, replyId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] });
      void queryClient.invalidateQueries({ queryKey: ["review-issues"] });
    },
  });
}

/** Edit a drafted reply's text. */
export function useEditReply() {
  const queryClient = useQueryClient();
  return useMutation<
    ReviewReplyDTO,
    Error,
    { channelId: string; replyId: string; replyText: string }
  >({
    mutationFn: ({ channelId, replyId, replyText }) => editReply(channelId, replyId, replyText),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}

/** Patch a review ticket (status, priority, notes, ...). */
export function useUpdateReviewIssue() {
  const queryClient = useQueryClient();
  return useMutation<ReviewIssue, Error, { id: string; patch: ReviewIssuePatch }>({
    mutationFn: ({ id, patch }) => updateReviewIssue(id, patch),
    onSuccess: (row) => {
      queryClient.setQueryData(
        ["review-issues", "list", "", true, 200],
        (old: { issues: ReviewIssue[]; total: number } | undefined) =>
          old ? { ...old, issues: old.issues.map((x) => (x.id === row.id ? row : x)) } : old,
      );
      void queryClient.invalidateQueries({ queryKey: ["review-issues"] });
    },
  });
}

/** Save a channel's auto-reply / response-engine config. */
export function useUpdateChannelConfig() {
  const queryClient = useQueryClient();
  return useMutation<
    unknown,
    Error,
    { channelId: string; body: Record<string, unknown> }
  >({
    mutationFn: async ({ channelId, body }) => {
      return apiFetch(`/api/v1/channels/${channelId}/autoreply`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
    },
    onSuccess: (_data, { channelId }) => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] });
      void queryClient.invalidateQueries({ queryKey: ["channels", "autoreply", channelId] });
    },
  });
}

/** Delete a channel connection. */
export function useDeleteChannel() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, { channelId: string }>({
    mutationFn: async ({ channelId }) => {
      await apiFetch(`/api/v1/channels/${channelId}`, { method: "DELETE" });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });
}