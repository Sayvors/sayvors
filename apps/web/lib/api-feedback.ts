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

export function submitFeedback(data: FeedbackCreate): Promise<Feedback> {
  return apiFetch("/api/v1/feedback", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
