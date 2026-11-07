import type { NextRequest } from "next/server";

/**
 * Streaming proxy for Ask Sayvors.
 *
 * The catch-all rewrite in `next.config.ts` forwards `/api/*` to FastAPI, but
 * a rewritten response is not safe for Server-Sent Events: the Next.js server
 * (and its compression layer) can hold chunks until the upstream stream ends,
 * which shipped every progress step and the finished answer in one paint.
 *
 * A route handler returns the upstream `ReadableStream` directly, so each SSE
 * frame reaches the browser the moment FastAPI writes it.
 *
 * Only used when the browser talks to the same origin (`API_BASE === ""`,
 * i.e. plain-http dev and the same-origin tunnel). Production points at the
 * API origin directly.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TARGET = (
  process.env.API_PROXY_TARGET ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

const SSE_HEADERS: Record<string, string> = {
  "content-type": "text/event-stream; charset=utf-8",
  "cache-control": "no-cache, no-transform",
  connection: "keep-alive",
  "x-accel-buffering": "no",
};

export async function POST(request: NextRequest) {
  const body = await request.text();
  const headers: Record<string, string> = {
    "content-type": request.headers.get("content-type") ?? "application/json",
    accept: "text/event-stream",
  };
  const cookie = request.headers.get("cookie");
  if (cookie) headers.cookie = cookie;
  const csrf = request.headers.get("x-csrf-token");
  if (csrf) headers["x-csrf-token"] = csrf;

  let upstream: Response;
  try {
    upstream = await fetch(`${TARGET}${request.nextUrl.pathname}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    return new Response(
      JSON.stringify({ detail: "Assistant is unavailable right now. Try again shortly." }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }

  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: SSE_HEADERS,
  });
}
