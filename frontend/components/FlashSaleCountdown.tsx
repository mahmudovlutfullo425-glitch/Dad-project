"use client";

import { useEffect, useState } from "react";
import { formatDuration } from "@/lib/format";

interface CountdownProps {
  startsAt: string;
  endsAt: string;
}

type Phase = "pre" | "live" | "post";

function compute(startsAt: number, endsAt: number) {
  const now = Date.now();
  let phase: Phase = "live";
  let target = endsAt;
  if (now < startsAt) {
    phase = "pre";
    target = startsAt;
  } else if (now >= endsAt) {
    phase = "post";
    target = endsAt;
  }
  return { phase, remaining: Math.max(0, target - now) };
}

export function FlashSaleCountdown({ startsAt, endsAt }: CountdownProps) {
  const start = new Date(startsAt).getTime();
  const end = new Date(endsAt).getTime();
  const [{ phase, remaining }, setState] = useState(() => compute(start, end));

  useEffect(() => {
    const tick = () => setState(compute(start, end));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [start, end]);

  if (phase === "post") {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
        Sale ended
      </span>
    );
  }

  const label = phase === "pre" ? "Starts in" : "Ends in";
  return (
    <span className="inline-flex items-center rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-900">
      {label} {formatDuration(remaining)}
    </span>
  );
}
