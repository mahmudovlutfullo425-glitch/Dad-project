import Link from "next/link";
import type { FlashSaleOut } from "@/lib/types";
import { FlashSaleCountdown } from "./FlashSaleCountdown";

interface FlashSaleBannerProps {
  sale: FlashSaleOut;
}

export function FlashSaleBanner({ sale }: FlashSaleBannerProps) {
  return (
    <Link
      href={`/flashsales/${sale.id}`}
      className="block rounded-lg border border-amber-300 bg-gradient-to-r from-amber-50 via-amber-100 to-amber-50 p-6 transition hover:shadow-md"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
            Flash sale
          </p>
          <h2 className="mt-1 text-xl font-bold text-amber-950">{sale.name}</h2>
          <p className="mt-1 text-sm text-amber-900">
            {sale.items.length} item{sale.items.length === 1 ? "" : "s"} at sale price
          </p>
        </div>
        <FlashSaleCountdown startsAt={sale.starts_at} endsAt={sale.ends_at} />
      </div>
    </Link>
  );
}
