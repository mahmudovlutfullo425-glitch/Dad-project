import { notFound } from "next/navigation";
import { AddToCartButton } from "@/components/AddToCartButton";
import { formatPrice } from "@/lib/format";
import { serverFetchOptional } from "@/lib/server-fetch";
import type { ProductOut } from "@/lib/types";

interface PageProps {
  params: { id: string };
}

export const dynamic = "force-dynamic";

export default async function ProductDetailPage({ params }: PageProps) {
  const id = Number.parseInt(params.id, 10);
  if (!Number.isFinite(id)) notFound();

  const product = await serverFetchOptional<ProductOut>(`/products/${id}`);
  if (product === null) notFound();

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[2fr_1fr]">
      <div className="space-y-4">
        <nav className="text-xs text-slate-500">
          <a href="/products" className="hover:text-brand">Products</a>
          <span className="mx-1">/</span>
          <a
            href={`/products?category=${product.category.slug}`}
            className="hover:text-brand"
          >
            {product.category.name}
          </a>
        </nav>
        <h1 className="text-3xl font-bold text-slate-900">{product.name}</h1>
        {product.brand && (
          <span className="tag">{product.brand}</span>
        )}
        <p className="whitespace-pre-line text-slate-700">{product.description}</p>
        {Object.keys(product.attributes ?? {}).length > 0 && (
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-slate-900">Details</h2>
            <dl className="mt-2 grid grid-cols-2 gap-y-1 text-sm">
              {Object.entries(product.attributes).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="capitalize text-slate-500">{k.replace(/_/g, " ")}</dt>
                  <dd className="text-slate-800">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <aside className="card space-y-4 p-6">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">From</p>
          <p className="text-3xl font-bold text-slate-900">
            {formatPrice(product.base_price)}
          </p>
        </div>
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-900">Variants</h2>
          {product.variants.length === 0 ? (
            <p className="text-sm text-slate-500">No variants available.</p>
          ) : (
            <ul className="space-y-2">
              {product.variants.map((v) => (
                <li
                  key={v.id}
                  className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2"
                >
                  <div>
                    <p className="text-sm font-medium text-slate-900">
                      {v.variant_name}
                    </p>
                    <p className="text-xs text-slate-500">SKU {v.sku}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-sm font-semibold text-slate-900">
                      {formatPrice(v.price)}
                    </span>
                    <AddToCartButton
                      variantId={v.id}
                      className="btn-primary text-xs"
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </div>
  );
}
