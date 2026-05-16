"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ToastProvider";
import { ApiError, type CartOut } from "@/lib/types";

interface AddToCartButtonProps {
  variantId: number;
  /** Optional label override — defaults to "Add to cart". */
  label?: string;
  className?: string;
}

export function AddToCartButton({ variantId, label, className }: AddToCartButtonProps) {
  const router = useRouter();
  const { user } = useAuth();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    if (!user) {
      // Bounce through login then come back; redirect target is the
      // current product page.
      const next = typeof window !== "undefined" ? window.location.pathname : "/";
      router.push(`/auth/login?next=${encodeURIComponent(next)}`);
      return;
    }
    setBusy(true);
    try {
      const updated = await api.post<CartOut>("/cart/items", {
        json: { variant_id: variantId, quantity: 1 },
      });
      // Push the fresh cart back into SWR so the navbar badge updates
      // without a refetch round-trip.
      mutate("/cart", updated, { revalidate: false });
      toast("Added to cart", "success");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not add to cart";
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={className ?? "btn-primary"}
    >
      {busy ? "Adding..." : (label ?? "Add to cart")}
    </button>
  );
}
