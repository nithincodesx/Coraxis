/**
 * Session storage — dual auth.
 *
 * Two sign-in paths, one session store:
 *
 * 1. Firebase (when NEXT_PUBLIC_FIREBASE_* is configured): the Firebase ID
 *    token is the bearer token, refreshed by the Firebase SDK.
 * 2. Local Coraxis accounts (fallback when Firebase is NOT configured, e.g.
 *    a Vercel deploy where the Firebase env vars were never set): the
 *    backend's own /auth/register|login endpoints return a Coraxis
 *    access/refresh token pair. Those tokens are stored here and the
 *    refresh token is rotated via /auth/refresh on a 401.
 *
 * Without path 2, a deployment missing Firebase config was a dead end:
 * every sign-in button threw "Firebase is not configured".
 */

import type { TokenPair, User } from "./types";
import {
  getCurrentFirebaseUser,
  getIdToken,
  isFirebaseConfigured,
  onAuthStateChange,
} from "./firebase";

const USER_KEY = "coraxis.user";
const ACCESS_KEY = "coraxis.access_token";
const REFRESH_KEY = "coraxis.refresh_token";

type Listener = (user: User | null) => void;
const listeners = new Set<Listener>();

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function getStoredUser(): User | null {
  if (!isBrowser()) return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function getLocalAccessToken(): string | null {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getLocalRefreshToken(): string | null {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function hasLocalSession(): boolean {
  return Boolean(getLocalAccessToken());
}

export function isAuthenticated(): boolean {
  return Boolean(getCurrentFirebaseUser()) || hasLocalSession();
}

function notify(user: User | null): void {
  for (const listener of listeners) listener(user);
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Persist the Coraxis user record, plus local tokens when supplied. */
export function persistSession(user: User, tokens?: TokenPair): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (tokens) {
    window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
    window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  }
  notify(user);
}

export function clearSession(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(USER_KEY);
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  notify(null);
}

/**
 * Rotate the local refresh token for a new access token.
 * Uses a raw fetch because lib/api.ts imports this module (circular import).
 * Returns the new access token, or null when there is no local session.
 */
async function refreshLocalToken(): Promise<string | null> {
  const refreshToken = getLocalRefreshToken();
  if (!refreshToken || !isBrowser()) return null;
  try {
    const response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (!response.ok) return null;
    const pair = (await response.json()) as TokenPair;
    persistSession(pair.user, pair);
    return pair.access_token;
  } catch {
    return null;
  }
}

export async function refreshAccessToken(): Promise<string | null> {
  if (hasLocalSession()) return refreshLocalToken();
  return getIdToken(true);
}

export async function getAccessToken(): Promise<string | null> {
  const local = getLocalAccessToken();
  if (local) return local;
  return getIdToken(false);
}

if (isBrowser() && isFirebaseConfigured()) {
  onAuthStateChange((firebaseUser) => {
    if (!firebaseUser && !hasLocalSession()) {
      clearSession();
    }
  });
}
