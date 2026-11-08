"use client";

/**
 * Authentication state backed by Firebase Auth.
 *
 * Firebase owns identity (GitHub OAuth, email/password). After signing in with
 * Firebase, the frontend calls `GET /api/v1/auth/me` (bearer = Firebase ID
 * token) to obtain the Coraxis account record — the backend creates it on
 * first sign-in, mapping the Firebase account to a user by email. That record
 * (with `display_name`, `is_superuser`, …) is what the shell renders.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import {
  signInWithEmail,
  signOut,
  signUpWithEmail,
} from "../lib/firebase";
import {
  getStoredUser,
  persistSession,
  clearSession,
  subscribe,
  isAuthenticated,
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
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const unsub = subscribe(setUser);

    // Confirm the stored session is still accepted. A Firebase ID token that
    // looks present but has been revoked must not leave the app rendering an
    // authenticated shell over 401s.
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
        if (!cancelled) setUser(getStoredUser());
      } finally {
        if (!cancelled) setIsReady(true);
      }
    };

    void verify();
    return () => {
      cancelled = true;
      unsub();
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    await signInWithEmail(email.trim(), password);
    const me = await api.auth.me();
    persistSession(me);
    setUser(me);
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      await signUpWithEmail(email.trim(), password, displayName.trim());
      const me = await api.auth.me();
      persistSession(me);
      setUser(me);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await signOut();
    } catch {
      // Ignored: sign out locally regardless of network.
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
