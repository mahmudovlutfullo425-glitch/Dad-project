/**
 * Server-side fetch helper for React Server Components.
 *
 * RSCs run inside the `frontend` container, so they hit the api
 * directly on the compose bridge network instead of routing through
 * the gateway. That avoids a TCP round-trip per request and skips
 * the gateway's per-process worker contention.
 *
 * Set INTERNAL_API_URL=http://api:8000 in the compose env (default).
 * NEXT_PUBLIC_API_URL stays pointed at /api for browser code.
 */
const INTERNAL_BASE = process.env.INTERNAL_API_URL ?? "http://api:8000";

export interface ServerFetchOpts extends Omit<RequestInit, "body"> {
  /** Cache strategy. Default: no-store for always-fresh reads. */
  revalidate?: number | false;
}

export async function serverFetch<T>(
  path: string,
  opts: ServerFetchOpts = {},
): Promise<T> {
  const { revalidate, ...rest } = opts;
  const cacheOpts: Partial<RequestInit> & { next?: { revalidate: number } } =
    revalidate === false
      ? { cache: "no-store" }
      : typeof revalidate === "number"
        ? { next: { revalidate } }
        : { cache: "no-store" };

  const res = await fetch(`${INTERNAL_BASE}${path}`, { ...rest, ...cacheOpts });
  if (!res.ok) {
    throw new Error(`serverFetch ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

/** Variant that returns null on 404 so RSC pages can render a "not found" state without throwing. */
export async function serverFetchOptional<T>(
  path: string,
  opts: ServerFetchOpts = {},
): Promise<T | null> {
  const { revalidate, ...rest } = opts;
  const cacheOpts: Partial<RequestInit> & { next?: { revalidate: number } } =
    revalidate === false
      ? { cache: "no-store" }
      : typeof revalidate === "number"
        ? { next: { revalidate } }
        : { cache: "no-store" };

  const res = await fetch(`${INTERNAL_BASE}${path}`, { ...rest, ...cacheOpts });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`serverFetch ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}
