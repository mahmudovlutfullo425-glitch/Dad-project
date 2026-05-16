"use client";

import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Pagination } from "@/components/Pagination";
import { swrFetcher } from "@/lib/api";
import type { InventoryList } from "@/lib/types";

export default function AdminInventoryPage() {
  const router = useRouter();
  const params = useSearchParams();
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const lowOnly = params.get("low_stock_only") === "true";

  const qp = new URLSearchParams({ page: String(page), page_size: "50" });
  if (lowOnly) qp.set("low_stock_only", "true");

  const { data, isLoading } = useSWR<InventoryList>(
    `/admin/inventory?${qp.toString()}`,
    swrFetcher,
  );

  const onToggle = () => {
    const sp = new URLSearchParams(params.toString());
    if (lowOnly) sp.delete("low_stock_only");
    else sp.set("low_stock_only", "true");
    sp.delete("page");
    router.push(`/admin/inventory?${sp.toString()}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900">Inventory levels</h1>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={lowOnly} onChange={onToggle} />
          <span>Low stock only</span>
        </label>
      </div>

      {isLoading && !data && <p className="text-sm text-slate-500">Loading...</p>}

      {data && (
        <>
          <p className="text-sm text-slate-500">{data.total} variants</p>
          <div className="card overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Variant</th>
                  <th className="px-3 py-2">SKU</th>
                  <th className="px-3 py-2">Product</th>
                  <th className="px-3 py-2 text-right">On hand</th>
                  <th className="px-3 py-2 text-right">Reserved</th>
                  <th className="px-3 py-2 text-right">Threshold</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {data.items.map((r) => {
                  const isLow = r.quantity_on_hand < r.low_stock_threshold;
                  return (
                    <tr key={r.variant_id} className={isLow ? "bg-red-50" : undefined}>
                      <td className="px-3 py-2 font-mono text-xs">#{r.variant_id}</td>
                      <td className="px-3 py-2 text-slate-600">{r.sku}</td>
                      <td className="px-3 py-2">
                        <span className="text-slate-900">{r.product_name}</span>
                        <span className="ml-1 text-xs text-slate-500">
                          ({r.variant_name})
                        </span>
                      </td>
                      <td className={`px-3 py-2 text-right ${isLow ? "font-semibold text-red-700" : ""}`}>
                        {r.quantity_on_hand}
                      </td>
                      <td className="px-3 py-2 text-right text-slate-600">
                        {r.quantity_reserved}
                      </td>
                      <td className="px-3 py-2 text-right text-slate-500">
                        {r.low_stock_threshold}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} />
        </>
      )}
    </div>
  );
}
