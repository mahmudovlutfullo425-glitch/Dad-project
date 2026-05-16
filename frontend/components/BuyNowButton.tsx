"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ToastProvider";
import { ApiError, type OrderOut } from "@/lib/types";

interface BuyNowButtonProps {
  flashSaleId: number;
  variantId: number;
  /** Default 1. The flash-sale item may have a per-user limit; the
   *  server returns 400 if exceeded, surfaced as an inline error. */
  quantity?: number;
  /** Disable the button when the countdown is in pre or post phase. */
  disabled?: boolean;
}

export function BuyNowButton({
  flashSaleId,
  variantId,
  quantity = 1,
  disabled = false,
}: BuyNowButtonProps) {
  const router = useRouter();
  const { user } = useAuth();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    if (!user) {
      const next = `/flashsales/${flashSaleId}`;
      router.push(`/auth/login?next=${encodeURIComponent(next)}`);
      return;
    }
    setBusy(true);
    try {
      const order = await api.post<OrderOut>(`/flashsales/${flashSaleId}/buy`, {
        json: { variant_id: variantId, quantity },
      });
      toast(`Order #${order.id} placed`, "success");
      router.push(`/orders/${order.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          const wait = err.retryAfter ?? 10;
          toast(`Slow down — try again in ${wait}s`, "error");
        } else if (err.status === 409) {
          toast("Sold out before we could place your order", "error");
        } else {
          toast(err.message || "Buy failed", "error");
        }
      } else {
        toast("Buy failed", "error");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      className="btn-primary text-base"
    >
      {busy ? "Placing..." : disabled ? "Not yet" : "Buy now"}
    </button>
  );
}
