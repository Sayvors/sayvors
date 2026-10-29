"use client";

import { API_BASE } from "./api-base";
import { useEffect, useRef } from "react";
import { refreshSession } from "@/lib/auth-context";

const API = API_BASE;

export interface NotificationPayload {
  kind: "message" | string;
  platform?: string | null;
  channel_id?: string | null;
  contact_id?: string | null;
  contact_name?: string | null;
  preview?: string | null;
  content_type?: string | null;
  message_id?: string | null;
  created_at?: string | null;
}

/** Ticket lifecycle changes. The payload identifies the row, not its
 *  contents — subscribers refetch rather than render from it, so a stale
 *  field can never render a wrong ticket. */
export type ReviewIssueAction =
  | "created"
  | "updated"
  | "customer_returned"
  | "handoff_minted";

export interface ReviewIssueEvent {
  id?: string | null;
  ticket_number?: string | null;
  status?: string | null;
  priority?: string | null;
  needs_attention?: boolean;
  primary_category?: string | null;
  subcategory?: string | null;
  rating?: number | null;
  has_handoff_code?: boolean;
}

export interface InboxRealtimeEvent {
  type:
    | "message"
    | "status"
    | "comment"
    | "comment_updated"
    | "comment_deleted"
    | "notification"
    | "review_issue"
    | "typing"
    | "mode"
    | "ping";
  notification?: NotificationPayload;
  id?: string;
  message_id?: string;
  channel_id?: string;
  platform?: string | null;
  direction?: "inbound" | "outbound";
  content?: string;
  content_type?: string;
  status?: "sent" | "delivered" | "read" | "failed";
  error?: string | null;
  contact_phone?: string | null;
  contact_name?: string | null;
  created_at?: string;
  /* typing events — who is composing in this thread right now */
  typing?: boolean;
  typing_source?: "ai" | "agent";
  /* conversation-mode events — another tab switched AI/human */
  mode?: "ai" | "human";
  mode_changed_at?: string | null;
  mode_changed_by?: string | null;
  /* comment events */
  comment_id?: string | null;
  parent_comment_id?: string | null;
  media_id?: string | null;
  author_id?: string | null;
  author_name?: string | null;
  hidden?: boolean;
  /* review ticket lifecycle: one ticket changed, refetch to see it */
  action?: ReviewIssueAction;
  issue?: ReviewIssueEvent;
}

/** Subscribe to live inbox events; auto-reconnects with backoff. */
export function useInboxRealtime(onEvent: (e: InboxRealtimeEvent) => void) {
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (closed) return;
      // Access token travels as httpOnly cookie — the browser sends it
      // automatically on same-origin WebSocket connections. No query param needed.
      const url = `${API.replace(/^http/, "ws")}/api/v1/inbox/ws`;
      ws = new WebSocket(url);
      ws.onopen = () => { attempt = 0; };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as InboxRealtimeEvent;
          if (data.type !== "ping") handler.current(data);
        } catch {}
      };
      ws.onclose = () => {
        if (closed) return;
        attempt = Math.min(attempt + 1, 5);
        const delay = Math.min(1000 * 2 ** (attempt - 1), 30000);
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => { ws?.close(); };
    }

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);
}
