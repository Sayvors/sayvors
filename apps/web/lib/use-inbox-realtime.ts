"use client";

import { useEffect, useRef } from "react";
import { getAccessToken } from "@/lib/auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface InboxRealtimeEvent {
  type: "message" | "status" | "ping";
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
      const token = getAccessToken();
      if (closed || !token) {
        if (!closed && !token) timer = setTimeout(connect, 2000);
        return;
      }
      const url = `${API.replace(/^http/, "ws")}/api/v1/inbox/ws?token=${encodeURIComponent(token)}`;
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
