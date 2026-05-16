"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { AddressPicker } from "@/components/AddressPicker";
import { ErrorBanner } from "@/components/ErrorBanner";
import { useToast } from "@/components/ToastProvider";
import { api, swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/format";
import { ApiError, type AddressOut, type CartOut, type OrderOut } from "@/lib/types";

export default function CheckoutPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { toast } = useToast();
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { data: cart } = useSWR<CartOut>(user ? "/cart" : null, swrFetcher);
  const { data: addresses } = useSWR<AddressOut[]>(
    user ? "/addresses" : null,
    swrFetcher,
  );

  // Default the radio to the user's primary address as soon as the list lands.
  useEffect(() => {
    if (selected !== null) return;
    if (!addresses || addresses.length === 0) return;
    const def = addresses.find((a) => a.is_default) ?? addresses[0];
    setSelected(def.id);
  }, [addresses, selected]);

  const lineItems = useMemo(() => cart?.items ?? [], [cart]);

  if (loading) return null;
  if (!user) {
    return (
      <div className="card space-y-3 p-6 text-center">
        <p className="text-slate-700">Sign in before checking out.</p>
        <Link
          href={`/auth/login?next=${encodeURIComponent("/checkout")}`}
          className="btn-primary"
        >
          Sign in
        </Link>
      </div>
    );
  }

  if (cart && cart.items.length === 0) {
    return (
      <div className="card space-y-3 p-6 text-center">
        <h1 className="text-xl font-semibold text-slate-900">Cart is empty</h1>
        <Link href="/products" className="btn-primary">
          Browse products
        </Link>
      </div>
    );
  }

  const onPlace = async () => {
    if (!selected) {
      setError("Pick a shipping address.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const order = await api.post<OrderOut>("/checkout", {
        json: { address_id: selected, payment_method: "card" },
      });
      // Cart is cleared server-side; clear the SWR cache so the badge
      // updates instantly.
      mutate("/cart", { items: [], subtotal: "0", item_count: 0 }, { revalidate: false });
      toast(`Order #${order.id} placed`, "success");
      router.push(`/orders/${order.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          setError(`Slow down — try again in ${err.retryAfter ?? 10}s.`);
        } else if (err.status === 409) {
          setError("Some items just sold out. Adjust your cart and try again.");
        } else {
          setError(err.message);
        }
      } else {
        setError("Checkout failed.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-900">Checkout</h1>
        {error && <ErrorBanner message={error} />}
        <div className="card p-4">
          <AddressPicker
            addresses={addresses ?? []}
            value={selected}
            onChange={setSelected}
          />
        </div>
      </div>

      <aside className="card space-y-3 p-4">
        <h2 className="text-sm font-semibold text-slate-900">Order summary</h2>
        <ul className="space-y-1 text-sm">
          {lineItems.map((it) => (
            <li key={it.variant_id} className="flex justify-between">
              <span className="text-slate-700">
                {it.name} × {it.quantity}
              </span>
              <span className="text-slate-900">{formatPrice(it.line_total)}</span>
            </li>
          ))}
        </ul>
        <hr />
        <div className="flex justify-between text-sm">
          <span className="text-slate-600">Subtotal</span>
          <span className="font-semibold text-slate-900">
            {formatPrice(cart?.subtotal ?? "0")}
          </span>
        </div>
        <button
          type="button"
          onClick={onPlace}
          disabled={submitting || !selected}
          className="btn-primary w-full"
        >
          {submitting ? "Placing..." : "Place order"}
        </button>
      </aside>
    </div>
  );
}
