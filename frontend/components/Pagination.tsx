"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
}

export function Pagination({ page, pageSize, total }: PaginationProps) {
  const pathname = usePathname();
  const params = useSearchParams();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const linkFor = (target: number) => {
    const sp = new URLSearchParams(params.toString());
    sp.set("page", String(target));
    return `${pathname}?${sp.toString()}`;
  };

  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-between gap-4 pt-4 text-sm text-slate-600">
      <span>
        Page {page} of {totalPages} ({total} total)
      </span>
      <div className="flex gap-2">
        {page > 1 ? (
          <Link href={linkFor(page - 1)} className="btn-secondary">
            Previous
          </Link>
        ) : (
          <span className="btn-secondary cursor-not-allowed opacity-50">Previous</span>
        )}
        {page < totalPages ? (
          <Link href={linkFor(page + 1)} className="btn-secondary">
            Next
          </Link>
        ) : (
          <span className="btn-secondary cursor-not-allowed opacity-50">Next</span>
        )}
      </div>
    </div>
  );
}
