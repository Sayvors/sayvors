"use client";

import { API_BASE } from "./api-base";
import { useEffect, useRef } from "react";

const API = API_BASE;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 60_000;
const MAX_RECONNECT_ATTEMPT = 8;
// Server sends a heartbeat every 25s; three missed beats are enough evidence
// that the client–server path is half-open. The browser's own WebSocket API
// does not expose an inactivity timeout, so the hook enforces one explicitly.
const HEARTBEAT_TIMEOUT_MS = 75_000;
const HEARTBEAT_CHECK_MS = 15_000;

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
    | "assignment"
    | "mode"
    | "blocked"
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
  reply_to_message_id?: string | null;
  media_url?: string | null;
  media_mime_type?: string | null;
  media_filename?: string | null;
  created_at?: string;
  /* typing events — who is composing in this thread right now */
  typing?: boolean;
  typing_source?: "ai" | "agent";
  /* conversation-mode events — another tab switched AI/human, or the
     escalation system did. The clock fields are present only on system
     events; a manual change always clears them. */
  mode?: "ai" | "human";
  mode_changed_at?: string | null;
  mode_changed_by?: string | null;
  /* provider-side block mirror (WA-6) */
  blocked_at?: string | null;
  blocked_by?: string | null;
  /* assignment events — who owns the conversation now */
  assigned_to?: string | null;
  assignee_name?: string | null;
  assigned_at?: string | null;
  priority?: "normal" | "important";
  ai_miss_count?: number;
  priority_since?: string | null;
  escalated_at?: string | null;
  escalation_reminder_at?: string | null;
  handover_sent_at?: string | null;
  resume_at?: string | null;
  escalation_resume_hours?: number;
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

/** Subscribe to live inbox events; auto-reconnects with full-jitter backoff. */
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
    let watchdog: ReturnType<typeof setInterval> | null = null;
    let lastSeenAt = 0;

    const online = () => typeof navigator === "undefined" || navigator.onLine;

    function reconnectDelay() {
      // Full jitter: wait a uniformly random interval up to the exponential
      // ceiling. This avoids every open dashboard reconnecting in lockstep
      // after an API restart overwhelms the server it is reconnecting to.
      const ceiling = Math.min(
        RECONNECT_BASE_MS * 2 ** Math.min(attempt - 1, 6),
        RECONNECT_MAX_MS,
      );
      return Math.floor(Math.random() * ceiling);
    }

    function clearWatchdog() {
      if (watchdog) clearInterval(watchdog);
      watchdog = null;
    }

    function armWatchdog() {
      clearWatchdog();
      watchdog = setInterval(() => {
        // Ignore hidden tabs: JS timers and socket events are throttled there,
        // which must not be mistaken for a half-open connection.
        if (document.visibilityState !== "visible") return;
        if (Date.now() - lastSeenAt > HEARTBEAT_TIMEOUT_MS) {
          // Closing triggers onclose, where the jittered reconnect is scheduled.
          ws?.close();
        }
      }, HEARTBEAT_CHECK_MS);
    }

    function scheduleReconnect() {
      if (closed || !online() || timer) return;
      attempt = Math.min(attempt + 1, MAX_RECONNECT_ATTEMPT);
      timer = setTimeout(() => {
        timer = null;
        connect();
      }, reconnectDelay());
    }

    function connect() {
      if (closed || !online()) return;
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        return;
      }
      // Access token travels as httpOnly cookie — the browser sends it
      // automatically on same-origin WebSocket connections. No query param needed.
      const url = `${API.replace(/^http/, "ws")}/api/v1/inbox/ws`;
      ws = new WebSocket(url);
      lastSeenAt = Date.now();
      ws.onopen = () => { attempt = 0; armWatchdog(); };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as InboxRealtimeEvent;
          lastSeenAt = Date.now();
          if (data.type === "ping") return;
          handler.current(data);
        } catch {
          // A malformed frame is not a reason to drop the live connection.
        }
      };
      ws.onclose = () => {
        ws = null;
        clearWatchdog();
        if (closed) return;
        scheduleReconnect();
      };
      ws.onerror = () => { ws?.close(); };
    }

    function handleOffline() {
      if (timer) clearTimeout(timer);
      timer = null;
      clearWatchdog();
      ws?.close();
      ws = null;
    }

    function handleOnline() {
      if (closed || (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING))) {
        return;
      }
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      // Reconnect immediately on recovery; jitter only applies to retries
      // after a close/error, not to an explicit browser "back online" event.
      connect();
    }

    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      clearWatchdog();
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
      ws?.close();
    };
  }, []);
}
