import { apiFetch } from "@/lib/api-rag";

export interface GoogleQuestion {
  id: string;
  channel_id: string;
  question_id: string;
  question_text: string;
  asker_name: string | null;
  asker_profile_photo_url: string | null;
  question_created_at: string | null;
  answer_text: string | null;
  answerer_name: string | null;
  answer_type: string | null;
  answer_created_at: string | null;
  last_synced_at: string | null;
  is_answered: boolean;
  is_ignored: boolean;
  upvote_count: number;
  draft_answer_text: string | null;
  draft_status: string;
  draft_error: string | null;
  draft_generated_at: string | null;
  draft_approved_at: string | null;
  created_at: string;
}

export interface GoogleQuestionPage {
  items: GoogleQuestion[];
  total: number;
  unanswered_count: number;
  ignored_count: number;
}

export async function fetchGoogleQuestions(params: {
  channelId?: string;
  answered?: boolean;
  ignored?: boolean;
  limit?: number;
} = {}): Promise<GoogleQuestionPage> {
  const q = new URLSearchParams();
  if (params.channelId) q.set("channel_id", params.channelId);
  if (params.answered !== undefined) q.set("answered", String(params.answered));
  if (params.ignored !== undefined) q.set("ignored", String(params.ignored));
  q.set("limit", String(params.limit ?? 50));
  const data = await apiFetch(`/api/v1/analytics/questions?${q.toString()}`);
  return {
    items: (data?.items ?? []) as GoogleQuestion[],
    total: Number(data?.total ?? 0),
    unanswered_count: Number(data?.unanswered_count ?? 0),
    ignored_count: Number(data?.ignored_count ?? 0),
  };
}

export async function draftGoogleAnswer(
  id: string,
  answerText?: string,
): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/draft`, {
    method: "POST",
    body: JSON.stringify(answerText ? { answer_text: answerText } : {}),
  })) as GoogleQuestion;
}

export async function editGoogleAnswerDraft(
  id: string,
  answerText: string,
): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/draft`, {
    method: "PATCH",
    body: JSON.stringify({ answer_text: answerText }),
  })) as GoogleQuestion;
}

export async function approveGoogleAnswer(id: string): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/approve`, {
    method: "POST",
  })) as GoogleQuestion;
}

export async function answerGoogleQuestion(
  id: string,
  answerText: string,
): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/answer`, {
    method: "POST",
    body: JSON.stringify({ answer_text: answerText }),
  })) as GoogleQuestion;
}

export async function rejectGoogleAnswerDraft(id: string): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/reject`, {
    method: "POST",
  })) as GoogleQuestion;
}

export async function ignoreGoogleQuestion(id: string): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/ignore`, {
    method: "POST",
  })) as GoogleQuestion;
}

export async function unignoreGoogleQuestion(id: string): Promise<GoogleQuestion> {
  return (await apiFetch(`/api/v1/analytics/questions/${encodeURIComponent(id)}/unignore`, {
    method: "POST",
  })) as GoogleQuestion;
}
