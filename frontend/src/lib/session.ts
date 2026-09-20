/**
 * Token storage and refresh.
 *
 * Tokens live in `localStorage` because the API is consumed cross-origin by
 * this Next.js app, where a cookie-based session would drag in CSRF handling
 * for no benefit. The tradeoff is real and worth stating: any script running on
 * this origin can read them, so the app must not be made to run untrusted
 * third-party scripts.
 *
 * The refresh path is single-flight. Refresh tokens are single-use and replaying
 * one is treated by the server as theft — it revokes every session for the user.
 * If two requests 401 simultaneously and both call refresh, the second one
 * presents an already-rotated token and logs the user out. Serialising refresh
 * behind one in-flight promise is what prevents the app from logging itself out
 * under normal concurrent load.
 */

import type { TokenPair, User } from "./types";

const ACCESS_KEY = "coraxis.access_token";
const REFRESH_KEY = "coraxis.refresh_token";
const USER_KEY = "coraxis.user";

type Listener = (user: User | null) => void;

const listeners = new Set<Listener>();

/** In-flight refresh, shared by every caller that asks while it is pending. */
let refreshInFlight: Promise<TokenPair | null> | null = null;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function getAccessToken(): string | null {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function getStoredUser(): User | null {
  if (!isBrowser()) return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    // A corrupted blob should log the user out, not crash the app on boot.
    return null;
  }
}

export function isAuthenticated(): boolean {
  return Boolean(getAccessToken());
}

function notify(user: User | null): void {
  for (const listener of listeners) listener(user);
}

/** Subscribe to sign-in/sign-out. Returns an unsubscribe function. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function persistSession(tokens: TokenPair): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(tokens.user));
  notify(tokens.user);
}

export function clearSession(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  window.localStorage.removeItem(USER_KEY);
  notify(null);
}

/**
 * Exchange the refresh token for a new pair.
 *
 * Concurrent callers share one request. Returns `null` when there is nothing to
 * refresh or the server refused, in which case the session is cleared — the
 * caller should treat that as "sign in again", not as a retryable error.
 */
export function refreshSession(basePath: string): Promise<TokenPair | null> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const refresh_token = getRefreshToken();
    if (!refresh_token) return null;

    try {
      const response = await fetch(`${basePath}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });

      if (!response.ok) {
        clearSession();
        return null;
      }

      const tokens = (await response.json()) as TokenPair;
      persistSession(tokens);
      return tokens;
    } catch {
      // A network blip is not proof the session is dead, so leave it intact and
      // let the caller surface a connection error.
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/**
 * Refresh and return just the access token, for the request retry path.
 *
 * Distinguishes "refreshed" from "refresh failed" so the client can decide
 * whether to retry once or to give up and surface the original 401.
 */
export async function refreshAccessToken(basePath: string): Promise<string | null> {
  const tokens = await refreshSession(basePath);
  return tokens?.access_token ?? null;
}
