"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { useAuth } from "@/lib/auth";
import { CartIcon } from "./CartIcon";

export function Navbar() {
  const router = useRouter();
  const { user, logout, loading } = useAuth();
  const [searchQuery, setSearchQuery] = useState("");

  const onSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    if (q.length === 0) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
  };

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
      <nav className="mx-auto flex w-full max-w-7xl items-center gap-6 px-4 py-3">
        <Link href="/" className="text-lg font-semibold text-brand-dark">
          FlashShop
        </Link>
        <Link href="/products" className="text-sm text-slate-700 hover:text-brand">
          Products
        </Link>
        <Link href="/search" className="text-sm text-slate-700 hover:text-brand">
          Search
        </Link>

        <form onSubmit={onSearchSubmit} className="ml-auto flex max-w-md flex-1">
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search products..."
            className="w-full rounded-l-md border-slate-300 text-sm focus:border-brand focus:ring-brand"
          />
          <button
            type="submit"
            className="rounded-r-md border border-l-0 border-slate-300 bg-slate-50 px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Go
          </button>
        </form>

        <CartIcon />

        {loading ? null : user ? (
          <div className="flex items-center gap-3">
            <Link href="/orders" className="text-sm text-slate-700 hover:text-brand">
              Orders
            </Link>
            {user.is_admin && (
              <Link href="/admin" className="text-sm font-semibold text-brand">
                Admin
              </Link>
            )}
            <span className="text-sm text-slate-500" title={user.email}>
              {user.full_name}
            </span>
            <button
              type="button"
              onClick={logout}
              className="text-sm text-slate-600 hover:text-red-600"
            >
              Sign out
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-sm">
            <Link href="/auth/login" className="text-slate-700 hover:text-brand">
              Sign in
            </Link>
            <Link href="/auth/register" className="btn-primary">
              Register
            </Link>
          </div>
        )}
      </nav>
    </header>
  );
}
