"use client";

import { useEffect } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Page error:", error);
  }, [error]);

  return (
    <div className="space-y-4">
      <ErrorBanner message={error.message || "Something went wrong."} />
      <button type="button" className="btn-secondary" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
