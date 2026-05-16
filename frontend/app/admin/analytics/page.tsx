"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { ErrorBanner } from "@/components/ErrorBanner";
import { swrFetcher } from "@/lib/api";
import type { FlashSaleAnalytics, FlashSaleOut } from "@/lib/types";

export default function AdminAnalyticsPage() {
  // Reuse the public listing — we don't have an admin-only flash-sale
  // catalogue endpoint and the data is identical (no PII).
  const { data: sales } = useSWR<FlashSaleOut[]>("/flashsales", swrFetcher);
  const [picked, setPicked] = useState<number | null>(null);

  // Default to the first sale once the list arrives. useEffect rather
  // than running the setter during render — the latter would re-fire
  // every render and trip React's "cannot update during render" guard.
  useEffect(() => {
    if (picked !== null) return;
    if (!sales || sales.length === 0) return;
    setPicked(sales[0].id);
  }, [sales, picked]);

  const { data: stats, error: statsError } = useSWR<FlashSaleAnalytics>(
    picked !== null ? `/admin/analytics/flashsales/${picked}` : null,
    swrFetcher,
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900">Flash-sale analytics</h1>
        <select
          value={picked ?? ""}
          onChange={(e) => setPicked(Number.parseInt(e.target.value, 10))}
          className="rounded-md text-sm"
          disabled={!sales || sales.length === 0}
        >
          {(sales ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              #{s.id} — {s.name}
            </option>
          ))}
        </select>
      </div>

      {sales && sales.length === 0 && (
        <p className="text-sm text-slate-500">
          No flash sales found. Run <code>make loadtest-flashsale</code> to create one.
        </p>
      )}

      {statsError && (
        <ErrorBanner
          message={
            (statsError as Error).message ||
            "Couldn't load ClickHouse stats — service may be down."
          }
        />
      )}

      {stats && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <section className="card p-4">
            <h2 className="text-sm font-semibold text-slate-900">Totals by action</h2>
            <table className="mt-2 w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-1">Action</th>
                  <th className="py-1 text-right">Events</th>
                  <th className="py-1 text-right">Quantity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {stats.totals.map((t) => (
                  <tr key={t.action}>
                    <td className="py-1 capitalize">{t.action}</td>
                    <td className="py-1 text-right">{t.events}</td>
                    <td className="py-1 text-right">{t.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card p-4">
            <h2 className="text-sm font-semibold text-slate-900">Latency (ms)</h2>
            <dl className="mt-2 grid grid-cols-4 gap-2 text-center text-sm">
              <div>
                <dt className="text-xs text-slate-500">p50</dt>
                <dd className="font-semibold">{stats.latency_ms.p50.toFixed(1)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">p95</dt>
                <dd className="font-semibold">{stats.latency_ms.p95.toFixed(1)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">p99</dt>
                <dd className="font-semibold">{stats.latency_ms.p99.toFixed(1)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">samples</dt>
                <dd className="font-semibold">{stats.latency_ms.samples}</dd>
              </div>
            </dl>
          </section>

          <section className="card p-4 lg:col-span-2">
            <h2 className="text-sm font-semibold text-slate-900">Rejection reasons</h2>
            {stats.rejections.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">No rejections recorded.</p>
            ) : (
              <table className="mt-2 w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="py-1">Reason</th>
                    <th className="py-1 text-right">Count</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {stats.rejections.map((r) => (
                    <tr key={r.rejection_reason || "unknown"}>
                      <td className="py-1">{r.rejection_reason || "(unknown)"}</td>
                      <td className="py-1 text-right">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card p-4 lg:col-span-2">
            <h2 className="text-sm font-semibold text-slate-900">Per-minute timeline</h2>
            {stats.timeline.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">No timeline rows.</p>
            ) : (
              <div className="mt-2 max-h-72 overflow-y-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="py-1">Minute</th>
                      <th className="py-1">Action</th>
                      <th className="py-1 text-right">Events</th>
                      <th className="py-1 text-right">Quantity</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {stats.timeline.map((row, i) => (
                      <tr key={`${row.minute}-${row.action}-${i}`}>
                        <td className="py-1 font-mono text-xs">{row.minute}</td>
                        <td className="py-1 capitalize">{row.action}</td>
                        <td className="py-1 text-right">{row.events}</td>
                        <td className="py-1 text-right">{row.quantity}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
