import { apiFetch } from "@/lib/api-rag";

export interface UiJob {
  id: string;
  job_type: string;
  lane: string;
  status: string;
  progress: number;
  progress_label: string | null;
  ui_title: string | null;
  ui_kind: string | null;
  ui_visible: boolean;
  ui_subject_type: string | null;
  ui_subject_id: string | null;
  error_code: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export async function fetchActiveUiJobs(signal?: AbortSignal): Promise<UiJob[]> {
  return apiFetch("/api/v1/jobs/active-ui", { signal });
}
