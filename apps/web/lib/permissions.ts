/**
 * Effective workspace permissions for the signed-in principal.
 *
 * `GET /api/v1/team/context` is the only endpoint that tells the client what
 * the current role may do. The shape has one trap: owners are never stored as
 * members, so their `permissions` list is deliberately empty and `is_owner`
 * is the entire answer. Every check here must therefore read
 * `is_owner || permissions.includes(...)`; testing the list alone would hide
 * owner-only affordances from the owner.
 *
 * The response is fetched once per page load and shared, including by
 * concurrent callers that arrive while the request is in flight. Roles change
 * server-side and the server re-checks every request, so a cache that lives
 * no longer than one document is safe.
 */
import { apiFetch } from "@/lib/api-rag";

export interface WorkspaceContext {
  is_owner: boolean;
  permissions: string[];
  channel_overrides: Record<string, string>;
}

let inflight: Promise<WorkspaceContext | null> | null = null;

export function loadWorkspaceContext(): Promise<WorkspaceContext | null> {
  inflight ??= apiFetch("/api/v1/team/context")
    .then((ctx) => ctx as WorkspaceContext)
    .catch(() => {
      // Fail closed: an unknown role must not be shown write-shaped actions.
      // Clearing the cache lets a later render retry instead of pinning the
      // page to "no permissions" after one flaky request.
      inflight = null;
      return null;
    });
  return inflight;
}

/** True when the principal holds `perm`. Owners hold every permission. */
export async function hasPermission(perm: string): Promise<boolean> {
  const ctx = await loadWorkspaceContext();
  return Boolean(ctx && (ctx.is_owner || ctx.permissions?.includes(perm)));
}
