"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ProductCard } from "@/components/ProductCard";
import { swrFetcher } from "@/lib/api";
import type { SearchResponse } from "@/lib/types";

/**
 * Tiny debounce hook — returns `value` after it has been stable for
 * `delay` ms. Used to throttle live-search keystrokes so we don't fire
 * a Meilisearch request on every character; users typing fast see one
 * request when they pause, not 10 mid-word.
 */
function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export default function SearchPage() {
  const router = useRouter();
  const params = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const brand = params.get("brand") ?? "";

  // `q` tracks the input value in real time; `debouncedQ` lags by
  // DEBOUNCE_MS and is what we actually search on + sync to the URL.
  const [q, setQ] = useState(urlQ);
  const debouncedQ = useDebouncedValue(q, 250);

  // Track which way the source of truth was last updated. When the URL
  // changes externally (back/forward, sidebar facet click), pull it
  // into the input. When the user types, we let the debounce → effect
  // chain push it out. Without this guard the two effects fight each
  // other on every keystroke.
  const lastSyncedRef = useRef<"input" | "url">("input");

  // URL → input (back/forward navigation, facet links).
  useEffect(() => {
    if (urlQ === q) return;
    lastSyncedRef.current = "url";
    setQ(urlQ);
  }, [urlQ]); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounced input → URL (live search).
  useEffect(() => {
    if (lastSyncedRef.current === "url") {
      lastSyncedRef.current = "input";
      return;
    }
    if (debouncedQ === urlQ) return;
    const sp = new URLSearchParams(params.toString());
    if (debouncedQ) sp.set("q", debouncedQ);
    else sp.delete("q");
    sp.delete("page");
    // replace (not push) so each keystroke doesn't pollute browser history.
    router.replace(`/search?${sp.toString()}`, { scroll: false });
  }, [debouncedQ]); // eslint-disable-line react-hooks/exhaustive-deps

  // SWR key — built from the debounced query + current filters. Keep
  // previous data while a new request is in flight so the result grid
  // doesn't flash empty between keystrokes.
  const qp = new URLSearchParams({ q: debouncedQ });
  if (category) qp.set("category_slug", category);
  if (brand) qp.set("brand", brand);
  qp.set("limit", "24");

  const { data, isLoading, error, isValidating } = useSWR<SearchResponse>(
    `/search/products?${qp.toString()}`,
    swrFetcher,
    { keepPreviousData: true },
  );

  // Pressing Enter forces the search through immediately, bypassing the
  // debounce. Useful when the user knows exactly what they want.
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const sp = new URLSearchParams(params.toString());
    if (q) sp.set("q", q);
    else sp.delete("q");
    sp.delete("page");
    router.push(`/search?${sp.toString()}`);
  };

  const filterLink = (key: string, value: string) => {
    const sp = new URLSearchParams(params.toString());
    if (sp.get(key) === value) sp.delete(key);
    else sp.set(key, value);
    return `/search?${sp.toString()}`;
  };

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="flex max-w-2xl gap-2">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search products (Meilisearch-powered) — results update as you type"
          autoFocus
          className="w-full rounded-md text-sm"
        />
        <button type="submit" className="btn-primary">
          Search
        </button>
      </form>

      {data && (
        <p className="text-xs text-slate-500">
          {data.total} hits in {data.took_ms} ms
          {isValidating && q !== debouncedQ && (
            <span className="ml-2 italic text-slate-400">updating…</span>
          )}
        </p>
      )}
      {error && (
        <p className="text-sm text-red-600">Search failed: {(error as Error).message}</p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
        <aside className="space-y-4">
          {data?.facets &&
            Object.entries(data.facets).map(([facet, counts]) => (
              <div key={facet}>
                <h3 className="text-sm font-semibold capitalize text-slate-900">
                  {facet.replace(/_/g, " ")}
                </h3>
                <ul className="mt-2 space-y-1 text-sm">
                  {Object.entries(counts)
                    .slice(0, 12)
                    .sort((a, b) => b[1] - a[1])
                    .map(([value, count]) => {
                      const paramKey =
                        facet === "category_name" ? "category" : facet;
                      const active = params.get(paramKey) === value;
                      return (
                        <li key={value}>
                          <Link
                            href={filterLink(paramKey, value)}
                            className={
                              active
                                ? "font-semibold text-brand"
                                : "text-slate-600 hover:text-brand"
                            }
                          >
                            {value}{" "}
                            <span className="text-xs text-slate-400">({count})</span>
                          </Link>
                        </li>
                      );
                    })}
                </ul>
              </div>
            ))}
        </aside>

        <div>
          {isLoading && !data && (
            <p className="text-sm text-slate-500">Searching...</p>
          )}
          {data && data.hits.length === 0 && debouncedQ && (
            <p className="text-sm text-slate-500">
              No hits for &ldquo;{debouncedQ}&rdquo;.
            </p>
          )}
          {data && data.hits.length === 0 && !debouncedQ && (
            <p className="text-sm text-slate-500">
              Start typing to search the catalog.
            </p>
          )}
          {data && data.hits.length > 0 && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.hits.map((h) => (
                <ProductCard key={h.id} product={h} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
