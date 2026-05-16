import Link from "next/link";

const tiles = [
  {
    href: "/admin/orders",
    title: "Orders",
    blurb: "All-orders list (paginated, filterable by status). Backed by GET /api/admin/orders.",
  },
  {
    href: "/admin/inventory",
    title: "Inventory",
    blurb: "Stock levels per variant, low-stock filter. Backed by GET /api/admin/inventory.",
  },
  {
    href: "/admin/analytics",
    title: "Analytics",
    blurb: "Flash-sale stats from ClickHouse: totals, timeline, rejection breakdown, latency.",
  },
];

export default function AdminHome() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">Admin</h1>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {tiles.map((t) => (
          <Link key={t.href} href={t.href} className="card p-5 transition hover:shadow-md">
            <h2 className="text-lg font-semibold text-brand-dark">{t.title}</h2>
            <p className="mt-1 text-sm text-slate-600">{t.blurb}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
