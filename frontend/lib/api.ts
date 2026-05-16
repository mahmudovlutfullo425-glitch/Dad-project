/**
 * Browser-side API client.
 *
 * All client components go through this wrapper so cross-cutting
 * concerns live in one place: bearer-token injection, 401-handling
 * (drop token + reload), 429-handling (raise a typed ApiError with
 * the Retry-After value so the UI can decide what to do).
 *
 * Server components must use {@link ./server-fetch} instead — they
 * have a different base URL (internal docker DNS, no gateway hop)
 * and don't have access to localStorage.
 */
import { ApiError } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const TOKEN_KEY = "jwt";

let memoToken: string | null | undefined = undefined;

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  if (memoToken === undefined) {
    memoToken = window.localStorage.getItem(TOKEN_KEY);
  }
  return memoToken;
}

export function setToken(token: string): void {
  memoToken = token;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.dispatchEvent(new CustomEvent("auth:changed"));
  }
}

export function clearToken(): void {
  memoToken = null;
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new CustomEvent("auth:changed"));
  }
}

interface RequestOpts extends Omit<RequestInit, "body"> {
  /** JSON-serialisable payload — converted + Content-Type set. */
  json?: unknown;
  /** Form-encoded body. Mutually exclusive with `json`. */
  form?: Record<string, string>;
  /** Skip auth header even when a token is present. */
  noAuth?: boolean;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const { json, form, noAuth, headers, ...rest } = opts;
  const h = new Headers(headers);

  let body: BodyInit | undefined;
  if (json !== undefined) {
    h.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    h.set("Content-Type", "application/x-www-form-urlencoded");
    body = new URLSearchParams(form).toString();
  }

  if (!noAuth) {
    const token = getToken();
    if (token) h.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...rest, headers: h, body });

  // 204 No Content — return undefined cast as T (callers that ask for
  // void are typed correctly; others would error obviously).
  if (res.status === 204) return undefined as T;

  let parsed: unknown = null;
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    parsed = await res.json().catch(() => null);
  } else {
    parsed = await res.text().catch(() => null);
  }

  if (!res.ok) {
    if (res.status === 401) {
      // Token rejected — drop it. AuthProvider listens for the event
      // and redirects to /auth/login.
      clearToken();
    }
    const retryAfterRaw = res.headers.get("Retry-After");
    const retryAfter = retryAfterRaw ? Number.parseInt(retryAfterRaw, 10) : null;
    const detail = extractDetail(parsed);
    throw new ApiError(res.status, detail, parsed, Number.isFinite(retryAfter) ? retryAfter : null);
  }
  return parsed as T;
}

function extractDetail(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    // Rate-limit middleware emits { detail: { error, rule, retry_after } }
    if (d && typeof d === "object") {
      return JSON.stringify(d);
    }
  }
  return typeof body === "string" && body ? body : "Request failed";
}

export const api = {
  get: <T,>(path: string, opts: RequestOpts = {}) => request<T>(path, { ...opts, method: "GET" }),
  post: <T,>(path: string, opts: RequestOpts = {}) => request<T>(path, { ...opts, method: "POST" }),
  patch: <T,>(path: string, opts: RequestOpts = {}) => request<T>(path, { ...opts, method: "PATCH" }),
  delete: <T,>(path: string, opts: RequestOpts = {}) => request<T>(path, { ...opts, method: "DELETE" }),
};

/** SWR fetcher — bound to the typed `api.get`. */
export const swrFetcher = <T,>(path: string) => api.get<T>(path);
