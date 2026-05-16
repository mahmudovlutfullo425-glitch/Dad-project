import Link from "next/link";
import { formatPrice } from "@/lib/format";
import type { ProductOut, SearchHit } from "@/lib/types";

interface ProductCardProps {
  product: ProductOut | SearchHit;
  href?: string;
}

function isFull(p: ProductOut | SearchHit): p is ProductOut {
  return (p as ProductOut).variants !== undefined;
}

export function ProductCard({ product, href }: ProductCardProps) {
  const linkHref = href ?? `/products/${product.id}`;
  const price = isFull(product) ? product.base_price : product.price;
  const category = isFull(product) ? product.category.name : product.category_name;
  const inStock = isFull(product) ? true : product.in_stock;

  return (
    <Link
      href={linkHref}
      className="card group flex h-full flex-col p-4 transition hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="line-clamp-2 text-sm font-semibold text-slate-900 group-hover:text-brand">
          {product.name}
        </h3>
      </div>
      <p className="mt-1 text-xs text-slate-500">{category}</p>
      {product.brand && (
        <span className="tag mt-2 self-start">{product.brand}</span>
      )}
      <div className="mt-auto flex items-end justify-between pt-3">
        <span className="text-base font-semibold text-slate-900">
          {formatPrice(price)}
        </span>
        {!inStock && (
          <span className="text-xs font-medium text-red-600">Out of stock</span>
        )}
      </div>
    </Link>
  );
}
