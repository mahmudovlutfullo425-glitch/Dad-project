"use client";

import Link from "next/link";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CartOut } from "@/lib/types";

export function CartIcon() {
  const { user } = useAuth();
  // Only fetch the cart when we have a user; SWR's conditional fetch
  // shape is the `null` key trick — passing null skips the request.
  const { data } = useSWR<CartOut>(user ? "/cart" : null, swrFetcher, {
    revalidateOnFocus: true,
    refreshInterval: 30_000,
  });
  const count = data?.item_count ?? 0;

  return (
    <Link href="/cart" className="relative inline-flex items-center text-slate-700 hover:text-brand">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        className="h-6 w-6"
        aria-hidden
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437m0 0 1.717 6.434a2.25 2.25 0 0 0 2.18 1.671h7.43a2.25 2.25 0 0 0 2.183-1.7l1.353-5.405a.75.75 0 0 0-.728-.932H5.106M16.5 19.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Zm-9 0a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z"
        />
      </svg>
      {count > 0 && (
        <span className="absolute -right-2 -top-2 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-brand px-1 text-[11px] font-semibold text-white">
          {count}
        </span>
      )}
    </Link>
  );
}
