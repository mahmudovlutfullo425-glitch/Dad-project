/**
 * AuthProvider — client-side auth state.
 *
 * Strategy is localStorage + bearer header. The token is verified
 * server-side on every request the api receives; the frontend only
 * decodes it (jose.decodeJwt — not verify) to read `sub` (user id)
 * and `exp` (auto-logout once expired).
 *
 * `is_admin` is NOT in the JWT — we fetch it from `/auth/me` once
 * after login + cache. That keeps the JWT compact and means an admin
 * can be revoked without re-issuing tokens.
 */
"use client";

import { decodeJwt } from "jose";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, clearToken, getToken, setToken } from "./api";
import type { TokenResponse, UserOut } from "./types";

interface AuthContextValue {
  user: UserOut | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    full_name: string,
  ) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function tokenIsLive(token: string): boolean {
  try {
    const { exp } = decodeJwt(token);
    if (typeof exp !== "number") return true;
    return exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);

  // Refresh the user profile from /auth/me. Called on mount + after login.
  const refreshMe = useCallback(async () => {
    const token = getToken();
    if (!token || !tokenIsLive(token)) {
      clearToken();
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.get<UserOut>("/auth/me");
      setUser(me);
    } catch {
      // 401 or network error — drop the token; api.ts already cleared on 401.
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshMe();
    // Listen for cross-component token changes (login from elsewhere, 401 clears).
    const onChange = () => refreshMe();
    window.addEventListener("auth:changed", onChange);
    return () => window.removeEventListener("auth:changed", onChange);
  }, [refreshMe]);

  const login = useCallback(async (email: string, password: string) => {
    const tok = await api.post<TokenResponse>("/auth/login", {
      form: { username: email, password },
      noAuth: true,
    });
    setToken(tok.access_token);
    await refreshMe();
  }, [refreshMe]);

  const register = useCallback(
    async (email: string, password: string, full_name: string) => {
      await api.post<UserOut>("/auth/register", {
        json: { email, password, full_name },
        noAuth: true,
      });
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    router.push("/");
  }, [router]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
