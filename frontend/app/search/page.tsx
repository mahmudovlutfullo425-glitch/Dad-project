"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import useSWR from "swr";
import { ProductCard } from "@/components/ProductCard";
import { swrFetcher } from "@/lib/api";
import type { SearchResponse } from "@/lib/types";

export default function SearchPage() {
  const router = useRouter();
  const params = useSearchParams();
  const initialQ = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const brand = params.get("brand") ?? "";
  const [q, setQ] = useState(initialQ);

  // Keep the input in sync if the user navigates back/forward.
  useEffect(() => {
    setQ(initialQ);
  }, [initialQ]);

  const qp = new URLSearchParams({ q: initialQ });
  if (category) qp.set("category_slug", category);
  if (brand) qp.set("brand", brand);
  qp.set("limit", "24");

  const { data, isLoading, error } = useSWR<SearchResponse>(
    `/search/products?${qp.toString()}`,
    swrFetcher,
    { keepPreviousData: true },
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const sp = new URLSearchParams(params.toString());
    sp.set("q", q);
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
          placeholder="Search products (Meilisearch-powered)"
          className="w-full rounded-md text-sm"
        />
        <button type="submit" className="btn-primary">
          Search
        </button>
      </form>

      {data && (
        <p className="text-xs text-slate-500">
          {data.total} hits in {data.took_ms} ms
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
          {data && data.hits.length === 0 && (
            <p className="text-sm text-slate-500">
              No hits for &ldquo;{initialQ}&rdquo;.
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
