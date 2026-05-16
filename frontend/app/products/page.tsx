import Link from "next/link";
import { Pagination } from "@/components/Pagination";
import { ProductCard } from "@/components/ProductCard";
import { serverFetch } from "@/lib/server-fetch";
import type { CategoryOut, ProductList } from "@/lib/types";

export const dynamic = "force-dynamic";

interface PageProps {
  searchParams: Record<string, string | string[] | undefined>;
}

function singleParam(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

export default async function ProductsPage({ searchParams }: PageProps) {
  const page = Math.max(1, Number.parseInt(singleParam(searchParams.page) ?? "1", 10) || 1);
  const categorySlug = singleParam(searchParams.category);
  const brand = singleParam(searchParams.brand);
  const minPrice = singleParam(searchParams.min_price);
  const maxPrice = singleParam(searchParams.max_price);

  const qp = new URLSearchParams({
    page: String(page),
    page_size: "20",
    is_active: "true",
  });
  if (categorySlug) qp.set("category_slug", categorySlug);
  if (brand) qp.set("brand", brand);
  if (minPrice) qp.set("min_price", minPrice);
  if (maxPrice) qp.set("max_price", maxPrice);

  const [products, categories] = await Promise.all([
    serverFetch<ProductList>(`/products?${qp.toString()}`),
    serverFetch<CategoryOut[]>("/categories"),
  ]);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[200px_1fr]">
      <aside className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Categories</h3>
          <ul className="mt-2 space-y-1 text-sm">
            <li>
              <Link
                href="/products"
                className={!categorySlug ? "font-semibold text-brand" : "text-slate-600 hover:text-brand"}
              >
                All categories
              </Link>
            </li>
            {categories.slice(0, 20).map((c) => (
              <li key={c.id}>
                <Link
                  href={`/products?category=${c.slug}`}
                  className={categorySlug === c.slug ? "font-semibold text-brand" : "text-slate-600 hover:text-brand"}
                >
                  {c.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <form action="/products" method="get" className="space-y-2 border-t border-slate-200 pt-4">
          <h3 className="text-sm font-semibold text-slate-900">Price</h3>
          <input
            type="hidden"
            name="category"
            value={categorySlug ?? ""}
          />
          <input
            type="number"
            name="min_price"
            min="0"
            placeholder="Min $"
            defaultValue={minPrice ?? ""}
            className="w-full rounded-md text-sm"
          />
          <input
            type="number"
            name="max_price"
            min="0"
            placeholder="Max $"
            defaultValue={maxPrice ?? ""}
            className="w-full rounded-md text-sm"
          />
          <button type="submit" className="btn-secondary w-full">
            Apply
          </button>
        </form>
      </aside>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-slate-900">Products</h1>
          <span className="text-sm text-slate-500">{products.total} total</span>
        </div>
        {products.items.length === 0 ? (
          <p className="text-sm text-slate-500">No products match those filters.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {products.items.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        )}
        <Pagination
          page={products.page}
          pageSize={products.page_size}
          total={products.total}
        />
      </div>
    </div>
  );
}
