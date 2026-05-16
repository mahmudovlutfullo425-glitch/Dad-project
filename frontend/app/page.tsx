import Link from "next/link";
import { FlashSaleBanner } from "@/components/FlashSaleBanner";
import { ProductCard } from "@/components/ProductCard";
import { serverFetch } from "@/lib/server-fetch";
import type { FlashSaleOut, ProductList } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  // Two parallel reads. Flash sales is the active list (server-side
  // filters to ends_at >= now); we surface the soonest-ending sale as
  // the banner. Products: first page sorted by id ascending — good
  // enough as "featured" until the catalog grows.
  const [salesRaw, productsRaw] = await Promise.allSettled([
    serverFetch<FlashSaleOut[]>("/flashsales"),
    serverFetch<ProductList>("/products?page=1&page_size=8&is_active=true"),
  ]);

  const sales = salesRaw.status === "fulfilled" ? salesRaw.value : [];
  const products = productsRaw.status === "fulfilled" ? productsRaw.value.items : [];

  // Pick the sale whose ends_at is soonest (most urgent) — empty list
  // → no banner.
  const featuredSale = sales
    .slice()
    .sort((a, b) => Date.parse(a.ends_at) - Date.parse(b.ends_at))[0];

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          FlashShop
        </h1>
        <p className="max-w-2xl text-slate-600">
          A working storefront for the Database Application &amp; Design
          project — real-time inventory backed by Redis, full-text search via
          Meilisearch, analytics in ClickHouse, and a token-bucket rate
          limiter we wrote from scratch.
        </p>
      </section>

      {featuredSale && <FlashSaleBanner sale={featuredSale} />}

      <section className="space-y-3">
        <div className="flex items-end justify-between">
          <h2 className="text-xl font-semibold text-slate-900">Featured products</h2>
          <Link href="/products" className="text-sm font-medium text-brand hover:text-brand-dark">
            Browse all →
          </Link>
        </div>
        {products.length === 0 ? (
          <p className="text-sm text-slate-500">
            No products available. Run <code>make seed</code> to load fixtures.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {products.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        )}
      </section>

      {sales.length > 1 && (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold text-slate-900">Other active sales</h2>
          <ul className="space-y-2">
            {sales
              .filter((s) => s.id !== featuredSale?.id)
              .map((s) => (
                <li key={s.id}>
                  <Link
                    href={`/flashsales/${s.id}`}
                    className="block rounded-md border border-slate-200 bg-white p-3 hover:border-brand"
                  >
                    {s.name} — {s.items.length} items
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      )}
    </div>
  );
}
