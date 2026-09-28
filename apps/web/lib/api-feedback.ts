"use client";

import { apiFetch } from "./api-rag";

export interface FeedbackCreate {
  emoji_rating: number;
  message?: string;
}

export interface Feedback {
  id: string;
  user_id: string;
  emoji_rating: number;
  message: string | null;
  created_at: string | null;
}

export interface FeedbackStatus {
  can_submit: boolean;
  last_submitted_at: string | null;
  cooldown_hours: number;
}

export function submitFeedback(data: FeedbackCreate): Promise<Feedback> {
  return apiFetch("/api/v1/feedback", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function fetchFeedbackStatus(): Promise<FeedbackStatus> {
  return (await apiFetch("/api/v1/feedback/status")) as FeedbackStatus;
}
