"use client";

/**
 * Authentication state — Firebase when configured, local Coraxis
 * accounts otherwise.
 *
 * Firebase path: sign in with the Firebase SDK, then GET /auth/me with the
 * Firebase ID token; the backend maps/creates the Coraxis user by email.
 *
 * Local fallback (no NEXT_PUBLIC_FIREBASE_* on the deployment): sign in
 * with the backend's own /auth/login|register, which return a Coraxis
 * token pair stored by lib/session.ts. This keeps a Firebase-less deploy
 * (the default Vercel state until env vars are set) fully usable instead
 * of dead-ending every sign-in with "Firebase is not configured".
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import {
  signInWithEmail,
  signInWithGitHub,
  signOut,
  signUpWithEmail,
  isFirebaseConfigured,
} from "../lib/firebase";
import {
  getStoredUser,
  persistSession,
  clearSession,
  subscribe,
  isAuthenticated,
  getLocalRefreshToken,
} from "../lib/session";
import type { User } from "../lib/types";

export interface UseAuthResult {
  user: User | null;
  isReady: boolean;
  isAuthenticated: boolean;
  firebaseConfigured: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithGitHub: () => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
}

export function useAuth(): UseAuthResult {
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const [isReady, setIsReady] = useState(false);
  const firebaseConfigured = isFirebaseConfigured();

  useEffect(() => {
    const unsub = subscribe(setUser);
    let cancelled = false;
    const verify = async () => {
      if (!isAuthenticated()) {
        if (!cancelled) setIsReady(true);
        return;
      }
      try {
        const me = await api.auth.me();
        if (!cancelled) {
          setUser(me);
          // Keep stored profile fresh without touching stored tokens.
          persistSession(me);
        }
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

  const login = useCallback(
    async (email: string, password: string) => {
      if (firebaseConfigured) {
        await signInWithEmail(email.trim(), password);
        const me = await api.auth.me();
        persistSession(me);
        setUser(me);
        return;
      }
      const pair = await api.auth.login({ email: email.trim(), password });
      persistSession(pair.user, pair);
      setUser(pair.user);
    },
    [firebaseConfigured],
  );

  const loginWithGitHub = useCallback(async () => {
    if (!firebaseConfigured) {
      throw new Error(
        "GitHub sign-in needs Firebase, which is not configured on this deployment. Use email + password, or set the NEXT_PUBLIC_FIREBASE_* variables and redeploy.",
      );
    }
    await signInWithGitHub();
    const me = await api.auth.me();
    persistSession(me);
    setUser(me);
  }, [firebaseConfigured]);

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      if (firebaseConfigured) {
        await signUpWithEmail(email.trim(), password, displayName.trim());
        const me = await api.auth.me();
        persistSession(me);
        setUser(me);
        return;
      }
      const pair = await api.auth.register({
        email: email.trim(),
        password,
        display_name: displayName.trim(),
      });
      persistSession(pair.user, pair);
      setUser(pair.user);
    },
    [firebaseConfigured],
  );

  const logout = useCallback(async () => {
    const refreshToken = getLocalRefreshToken();
    if (refreshToken) {
      try {
        await api.auth.logoutLocal(refreshToken);
      } catch {
        // Ignored: sign out locally regardless.
      }
    }
    if (firebaseConfigured) {
      try {
        await signOut();
      } catch {
        // Ignored.
      }
    }
    clearSession();
    setUser(null);
  }, [firebaseConfigured]);

  return {
    user,
    isReady,
    isAuthenticated: Boolean(user),
    firebaseConfigured,
    login,
    loginWithGitHub,
    register,
    logout,
  };
}
