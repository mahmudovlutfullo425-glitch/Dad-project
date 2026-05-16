"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { api, swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ToastProvider";
import { formatPrice } from "@/lib/format";
import { ApiError, type CartOut } from "@/lib/types";

export default function CartPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { toast } = useToast();
  const { data, isLoading } = useSWR<CartOut>(
    user ? "/cart" : null,
    swrFetcher,
  );

  if (loading) return null;
  if (!user) {
    return (
      <div className="card space-y-3 p-6 text-center">
        <p className="text-slate-700">Sign in to see your cart.</p>
        <Link
          href={`/auth/login?next=${encodeURIComponent("/cart")}`}
          className="btn-primary"
        >
          Sign in
        </Link>
      </div>
    );
  }

  const updateQuantity = async (variantId: number, quantity: number) => {
    try {
      const fresh = await api.patch<CartOut>(`/cart/items/${variantId}`, {
        json: { quantity },
      });
      mutate("/cart", fresh, { revalidate: false });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Update failed", "error");
    }
  };

  const removeItem = async (variantId: number) => {
    try {
      const fresh = await api.delete<CartOut>(`/cart/items/${variantId}`);
      mutate("/cart", fresh, { revalidate: false });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Remove failed", "error");
    }
  };

  const clearCart = async () => {
    try {
      await api.delete<void>("/cart");
      mutate("/cart", { items: [], subtotal: "0", item_count: 0 }, { revalidate: false });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Clear failed", "error");
    }
  };

  if (isLoading && !data) {
    return <p className="text-sm text-slate-500">Loading cart...</p>;
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="card space-y-3 p-6 text-center">
        <h1 className="text-xl font-semibold text-slate-900">Your cart is empty</h1>
        <p className="text-slate-600">Browse the catalog and add a product.</p>
        <Link href="/products" className="btn-primary">
          Browse products
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Your cart</h1>
        <button type="button" onClick={clearCart} className="text-sm text-red-600 hover:underline">
          Clear cart
        </button>
      </div>

      <ul className="space-y-2">
        {data.items.map((item) => (
          <li key={item.variant_id} className="card flex items-center gap-4 p-4">
            <div className="flex-1">
              <p className="font-medium text-slate-900">{item.name}</p>
              <p className="text-xs text-slate-500">SKU {item.sku}</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => updateQuantity(item.variant_id, item.quantity - 1)}
                disabled={item.quantity <= 1}
                className="btn-secondary px-3 py-1 text-xs"
                aria-label="Decrease"
              >
                −
              </button>
              <span className="w-8 text-center text-sm">{item.quantity}</span>
              <button
                type="button"
                onClick={() => updateQuantity(item.variant_id, item.quantity + 1)}
                className="btn-secondary px-3 py-1 text-xs"
                aria-label="Increase"
              >
                +
              </button>
            </div>
            <div className="w-24 text-right text-sm">
              <p className="text-slate-900">{formatPrice(item.line_total)}</p>
              <p className="text-xs text-slate-500">@{formatPrice(item.unit_price)}</p>
            </div>
            <button
              type="button"
              onClick={() => removeItem(item.variant_id)}
              className="text-xs text-red-600 hover:underline"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="card flex items-center justify-between p-4">
        <div>
          <p className="text-sm text-slate-500">Subtotal ({data.item_count} items)</p>
          <p className="text-xl font-semibold text-slate-900">
            {formatPrice(data.subtotal)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push("/checkout")}
          className="btn-primary"
        >
          Checkout
        </button>
      </div>
    </div>
  );
}
