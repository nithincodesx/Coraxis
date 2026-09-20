"use client";

/**
 * Authentication state.
 *
 * The session lives in `localStorage` (see `lib/session.ts`) and this hook is
 * the React view of it. It subscribes to the store rather than duplicating it,
 * so a token cleared by a failed refresh in `lib/api.ts` propagates here and
 * the UI falls back to the sign-in screen on its own.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import {
  clearSession,
  getStoredUser,
  isAuthenticated,
  persistSession,
  subscribe,
} from "../lib/session";
import type { User } from "../lib/types";

export interface UseAuthResult {
  user: User | null;
  /** False until the stored session has been checked against the server. */
  isReady: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
}

export function useAuth(): UseAuthResult {
  // Seeded lazily from the store rather than assigned in an effect, which
  // would cause a second render on every mount. `isReady` gates rendering
  // until the session has been checked, so a server/client mismatch in the
  // stored value cannot reach the DOM.
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const [isReady, setIsReady] = useState(false);

  useEffect(() => subscribe(setUser), []);

  // Confirm the stored token is still accepted. A token that looks present but
  // has been revoked (password change, reuse detection, expiry) must not leave
  // the app rendering an authenticated shell over 401s.
  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      if (!isAuthenticated()) {
        if (!cancelled) setIsReady(true);
        return;
      }
      try {
        const me = await api.auth.me();
        if (!cancelled) setUser(me);
      } catch {
        // The client already cleared the session on an unrecoverable 401.
        if (!cancelled) setUser(getStoredUser());
      } finally {
        if (!cancelled) setIsReady(true);
      }
    };

    void verify();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api.auth.login({ email, password });
    persistSession(tokens);
    setUser(tokens.user);
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      const tokens = await api.auth.register({
        email,
        password,
        display_name: displayName,
      });
      persistSession(tokens);
      setUser(tokens.user);
    },
    [],
  );

  const logout = useCallback(async () => {
    const { getRefreshToken } = await import("../lib/session");
    const refresh_token = getRefreshToken() ?? undefined;
    try {
      // Best effort: revoke server-side, but never block signing out locally on
      // a network failure.
      await api.auth.logout({ refresh_token });
    } catch {
      // Ignored on purpose.
    }
    clearSession();
    setUser(null);
  }, []);

  return {
    user,
    isReady,
    isAuthenticated: Boolean(user),
    login,
    register,
    logout,
  };
}
