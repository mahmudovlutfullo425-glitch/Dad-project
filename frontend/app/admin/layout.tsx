"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace(`/auth/login?next=${encodeURIComponent("/admin")}`);
      return;
    }
    if (!user.is_admin) {
      router.replace("/");
    }
  }, [user, loading, router]);

  if (loading || !user || !user.is_admin) {
    return <p className="text-sm text-slate-500">Checking admin access...</p>;
  }

  return (
    <div className="space-y-4">
      <nav className="flex flex-wrap gap-3 border-b border-slate-200 pb-3 text-sm">
        <Link href="/admin" className="font-semibold text-brand">Admin</Link>
        <Link href="/admin/orders" className="text-slate-700 hover:text-brand">Orders</Link>
        <Link href="/admin/inventory" className="text-slate-700 hover:text-brand">Inventory</Link>
        <Link href="/admin/analytics" className="text-slate-700 hover:text-brand">Analytics</Link>
      </nav>
      {children}
    </div>
  );
}
