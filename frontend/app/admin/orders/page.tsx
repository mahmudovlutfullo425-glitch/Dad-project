"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Pagination } from "@/components/Pagination";
import { swrFetcher } from "@/lib/api";
import { formatDateTime, formatPrice } from "@/lib/format";
import type { OrderList } from "@/lib/types";

const STATUS_OPTIONS: Array<"all" | "pending" | "paid" | "fulfilling" | "shipped" | "delivered" | "cancelled"> = [
  "all",
  "pending",
  "paid",
  "fulfilling",
  "shipped",
  "delivered",
  "cancelled",
];

export default function AdminOrdersPage() {
  const router = useRouter();
  const params = useSearchParams();
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const status = params.get("status") ?? "all";

  const qp = new URLSearchParams({ page: String(page), page_size: "30" });
  if (status !== "all") qp.set("status", status);

  const { data, isLoading } = useSWR<OrderList>(
    `/admin/orders?${qp.toString()}`,
    swrFetcher,
    { refreshInterval: 10_000 },
  );

  const onStatusChange = (next: string) => {
    const sp = new URLSearchParams(params.toString());
    if (next === "all") sp.delete("status");
    else sp.set("status", next);
    sp.delete("page");
    router.push(`/admin/orders?${sp.toString()}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900">All orders</h1>
        <select
          value={status}
          onChange={(e) => onStatusChange(e.target.value)}
          className="rounded-md text-sm"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All statuses" : s}
            </option>
          ))}
        </select>
      </div>

      {isLoading && !data && <p className="text-sm text-slate-500">Loading...</p>}

      {data && (
        <>
          <div className="card overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Order</th>
                  <th className="px-3 py-2">Placed</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Items</th>
                  <th className="px-3 py-2 text-right">Total</th>
                  <th className="px-3 py-2">Flash sale</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {data.items.map((o) => (
                  <tr key={o.id}>
                    <td className="px-3 py-2 font-mono text-xs">#{o.id}</td>
                    <td className="px-3 py-2 text-slate-600">{formatDateTime(o.placed_at)}</td>
                    <td className="px-3 py-2 capitalize">{o.status}</td>
                    <td className="px-3 py-2">{o.items.length}</td>
                    <td className="px-3 py-2 text-right">{formatPrice(o.total)}</td>
                    <td className="px-3 py-2 text-slate-500">
                      {o.flash_sale_id ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Link
                        href={`/orders/${o.id}`}
                        className="text-sm text-brand hover:underline"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} />
        </>
      )}
    </div>
  );
}
