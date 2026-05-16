"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Pagination } from "@/components/Pagination";
import { swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatPrice } from "@/lib/format";
import type { OrderList } from "@/lib/types";

const statusBadge: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  paid: "bg-blue-100 text-blue-800",
  fulfilling: "bg-emerald-100 text-emerald-800",
  shipped: "bg-indigo-100 text-indigo-800",
  delivered: "bg-green-100 text-green-800",
  cancelled: "bg-red-100 text-red-800",
};

export default function OrdersPage() {
  const { user, loading } = useAuth();
  const params = useSearchParams();
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const { data } = useSWR<OrderList>(
    user ? `/orders?page=${page}&page_size=20` : null,
    swrFetcher,
    { refreshInterval: 5000 },
  );

  if (loading) return null;
  if (!user) {
    return (
      <div className="card p-6 text-center text-slate-700">
        Sign in to see your orders.
      </div>
    );
  }
  if (!data) return <p className="text-sm text-slate-500">Loading orders...</p>;
  if (data.items.length === 0) {
    return (
      <div className="card space-y-3 p-6 text-center">
        <h1 className="text-xl font-semibold text-slate-900">No orders yet</h1>
        <Link href="/products" className="btn-primary">
          Browse products
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">Your orders</h1>
      <div className="card overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Order</th>
              <th className="px-3 py-2">Placed</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Items</th>
              <th className="px-3 py-2 text-right">Total</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {data.items.map((o) => (
              <tr key={o.id}>
                <td className="px-3 py-2 font-mono text-xs text-slate-700">#{o.id}</td>
                <td className="px-3 py-2 text-slate-600">{formatDateTime(o.placed_at)}</td>
                <td className="px-3 py-2">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge[o.status] ?? "bg-slate-100 text-slate-800"}`}>
                    {o.status}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-700">{o.items.length}</td>
                <td className="px-3 py-2 text-right font-semibold text-slate-900">
                  {formatPrice(o.total)}
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
    </div>
  );
}
