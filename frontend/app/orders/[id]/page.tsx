"use client";

import Link from "next/link";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatPrice } from "@/lib/format";
import type { OrderOut } from "@/lib/types";

const STATUS_FLOW = ["pending", "paid", "fulfilling", "shipped", "delivered"];

export default function OrderDetailPage({ params }: { params: { id: string } }) {
  const { user, loading } = useAuth();
  const orderId = params.id;
  const { data, error } = useSWR<OrderOut>(
    user ? `/orders/${orderId}` : null,
    swrFetcher,
    // Poll every 3 s while the order is pending/paid so the user sees
    // the Celery chain advance without manual refresh.
    {
      refreshInterval: (latest) => {
        const status = latest?.status;
        if (!status) return 0;
        const terminal = ["delivered", "cancelled"];
        return terminal.includes(status) ? 0 : 3000;
      },
    },
  );

  if (loading) return null;
  if (!user) return <p className="text-slate-700">Sign in to view this order.</p>;
  if (error) return <p className="text-sm text-red-600">Order not found.</p>;
  if (!data) return <p className="text-sm text-slate-500">Loading order...</p>;

  const stepIndex = STATUS_FLOW.indexOf(data.status);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Order #{data.id}</h1>
          <p className="text-sm text-slate-500">Placed {formatDateTime(data.placed_at)}</p>
        </div>
        <Link href="/orders" className="text-sm text-brand hover:underline">
          ← All orders
        </Link>
      </div>

      <div className="card p-4">
        <h2 className="text-sm font-semibold text-slate-900">Status</h2>
        <ol className="mt-3 flex flex-wrap gap-3">
          {STATUS_FLOW.map((s, i) => (
            <li
              key={s}
              className={`flex items-center gap-2 text-sm ${
                i <= stepIndex ? "text-brand-dark" : "text-slate-400"
              }`}
            >
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                  i <= stepIndex ? "bg-brand text-white" : "bg-slate-200 text-slate-500"
                }`}
              >
                {i + 1}
              </span>
              <span className="capitalize">{s}</span>
            </li>
          ))}
        </ol>
        {data.status === "cancelled" && (
          <p className="mt-3 text-sm text-red-600">This order was cancelled.</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-slate-900">Items</h2>
          <ul className="mt-2 divide-y divide-slate-200 text-sm">
            {data.items.map((it) => (
              <li key={it.variant_id} className="flex justify-between py-2">
                <span className="text-slate-700">
                  Variant {it.variant_id} × {it.quantity}
                </span>
                <span className="text-slate-900">{formatPrice(it.line_total)}</span>
              </li>
            ))}
          </ul>
        </div>
        <aside className="card space-y-2 p-4 text-sm">
          <h2 className="text-sm font-semibold text-slate-900">Totals</h2>
          <div className="flex justify-between">
            <span className="text-slate-600">Subtotal</span>
            <span>{formatPrice(data.subtotal)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-600">Shipping</span>
            <span>{formatPrice(data.shipping_fee)}</span>
          </div>
          <hr />
          <div className="flex justify-between text-base font-semibold text-slate-900">
            <span>Total</span>
            <span>{formatPrice(data.total)}</span>
          </div>
          {data.payment && (
            <p className="pt-2 text-xs text-slate-500">
              Payment {data.payment.status} ({data.payment.currency} {data.payment.amount})
            </p>
          )}
          {data.flash_sale_id !== null && (
            <p className="text-xs text-amber-700">
              Flash-sale purchase (sale #{data.flash_sale_id})
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
