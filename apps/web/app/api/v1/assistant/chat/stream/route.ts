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

// Where the local FastAPI process listens. Deliberately NOT
// NEXT_PUBLIC_API_URL: in dev that points at the public tunnel hostname, so
// proxying there from inside this server would loop back into Next (or hang
// when the tunnel is unreachable). Override only with a local target.
const TARGET = (process.env.API_PROXY_TARGET || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

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
  const controller = new AbortController();
  // Bound only the wait for response headers. Once FastAPI answers, the
  // timer is cleared so the event stream itself is never aborted.
  const headerTimeout = setTimeout(() => controller.abort(), 20_000);
  try {
    upstream = await fetch(`${TARGET}${request.nextUrl.pathname}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch {
    return new Response(
      JSON.stringify({ detail: "Assistant is unavailable right now. Try again shortly." }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  } finally {
    clearTimeout(headerTimeout);
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
