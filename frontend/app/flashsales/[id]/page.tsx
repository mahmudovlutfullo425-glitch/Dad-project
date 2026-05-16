import Link from "next/link";
import { notFound } from "next/navigation";
import { BuyNowButton } from "@/components/BuyNowButton";
import { FlashSaleCountdown } from "@/components/FlashSaleCountdown";
import { formatDateTime, formatPrice } from "@/lib/format";
import { serverFetchOptional } from "@/lib/server-fetch";
import type { FlashSaleOut } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function FlashSalePage({ params }: { params: { id: string } }) {
  const id = Number.parseInt(params.id, 10);
  if (!Number.isFinite(id)) notFound();

  const sale = await serverFetchOptional<FlashSaleOut>(`/flashsales/${id}`);
  if (!sale) notFound();

  // We can't know the live state at request time (the user clock is
  // authoritative for the countdown), but we can pre-compute whether
  // the sale is fundamentally over so the SSR markup matches what the
  // client will render after first paint.
  const ended = sale.status === "ended" || sale.status === "cancelled";

  return (
    <div className="space-y-6">
      <nav className="text-xs text-slate-500">
        <Link href="/" className="hover:text-brand">Home</Link>
        <span className="mx-1">/</span>
        <span>Flash sale</span>
      </nav>

      <header className="card flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-amber-50 via-amber-100 to-amber-50 p-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
            Flash sale
          </p>
          <h1 className="mt-1 text-2xl font-bold text-amber-950">{sale.name}</h1>
          <p className="mt-2 text-sm text-amber-900">
            Starts {formatDateTime(sale.starts_at)} · ends{" "}
            {formatDateTime(sale.ends_at)}
          </p>
        </div>
        <FlashSaleCountdown startsAt={sale.starts_at} endsAt={sale.ends_at} />
      </header>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-slate-900">Items in this sale</h2>
        {sale.items.length === 0 ? (
          <p className="text-sm text-slate-500">No items configured.</p>
        ) : (
          <ul className="space-y-2">
            {sale.items.map((it) => (
              <li
                key={it.id}
                className="card flex flex-wrap items-center justify-between gap-3 p-4"
              >
                <div>
                  <p className="text-sm font-medium text-slate-900">
                    Variant #{it.variant_id}
                  </p>
                  <p className="text-xs text-slate-500">
                    Per-user limit {it.per_user_limit} · {it.quantity_allocated} allocated
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-lg font-semibold text-slate-900">
                    {formatPrice(it.sale_price)}
                  </span>
                  <BuyNowButton
                    flashSaleId={sale.id}
                    variantId={it.variant_id}
                    disabled={ended}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-xs text-slate-500">
        Buy attempts are rate-limited per user (the token-bucket limiter we
        wrote from scratch — see <code>inventory/app/ratelimit/</code>). If
        you click too fast, you&apos;ll get a toast asking you to slow down.
      </p>
    </div>
  );
}
