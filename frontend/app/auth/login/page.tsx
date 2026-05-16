"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/";
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push(next);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          setError(`Too many attempts — try again in ${err.retryAfter ?? 20}s.`);
        } else if (err.status === 401) {
          setError("Wrong email or password.");
        } else {
          setError(err.message);
        }
      } else {
        setError("Login failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <div className="card space-y-4 p-6">
        <h1 className="text-2xl font-bold text-slate-900">Sign in</h1>
        {error && <ErrorBanner message={error} />}
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-700">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md"
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-700">Password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md"
            />
          </label>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Signing in..." : "Sign in"}
          </button>
        </form>
        <p className="text-center text-sm text-slate-600">
          No account?{" "}
          <Link
            href={`/auth/register?next=${encodeURIComponent(next)}`}
            className="text-brand hover:underline"
          >
            Register
          </Link>
        </p>
        <p className="text-center text-xs text-slate-400">
          Demo: <code>user1@ecom.local</code> / <code>user1234</code> ·
          admin: <code>admin@ecom.local</code> / <code>admin123</code>
        </p>
      </div>
    </div>
  );
}
