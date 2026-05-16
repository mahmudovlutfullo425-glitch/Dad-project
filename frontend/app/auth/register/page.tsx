"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/types";

export default function RegisterPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/";
  const { register } = useAuth();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      await register(email, password, fullName);
      router.push(next);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError("That email is already registered. Try signing in.");
        } else {
          setError(err.message);
        }
      } else {
        setError("Registration failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <div className="card space-y-4 p-6">
        <h1 className="text-2xl font-bold text-slate-900">Create an account</h1>
        {error && <ErrorBanner message={error} />}
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-700">Full name</span>
            <input
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="mt-1 w-full rounded-md"
            />
          </label>
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
            <span className="text-slate-700">Password (≥ 8 chars)</span>
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md"
            />
          </label>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Creating..." : "Register"}
          </button>
        </form>
        <p className="text-center text-sm text-slate-600">
          Already have an account?{" "}
          <Link
            href={`/auth/login?next=${encodeURIComponent(next)}`}
            className="text-brand hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
