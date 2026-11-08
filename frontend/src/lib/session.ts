/**
 * Firebase session storage.
 *
 * The Firebase ID token is attached as the `Authorization: Bearer` header on
 * every API request (see `lib/api.ts`). Firebase's client SDK keeps the token
 * refreshed; `getAccessToken` forces a refresh when a request comes back 401,
 * so a stale token is retried once against Firebase's auth servers before the
 * session is treated as dead.
 *
 * The persisted profile is the Coraxis `User` record (fetched from
 * `GET /api/v1/auth/me` after a Firebase sign-in), so the shell renders
 * `display_name`, `is_superuser`, etc.
 *
 * Tokens live in `localStorage` because the API is consumed cross-origin by
 * this Next.js app. Any script on this origin can read them — do not run
 * untrusted third-party scripts here.
 */

import type { User } from "./types";
import {
  getCurrentFirebaseUser,
  getIdToken,
  isFirebaseConfigured,
  onAuthStateChange,
} from "./firebase";

const USER_KEY = "coraxis.user";

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
    // A corrupted blob should log the user out, not crash the app on boot.
    return null;
  }
}

export function isAuthenticated(): boolean {
  return Boolean(getCurrentFirebaseUser());
}

function notify(user: User | null): void {
  for (const listener of listeners) listener(user);
}

/** Subscribe to sign-in/sign-out. Returns an unsubscribe function. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Persist the Coraxis user record obtained after a Firebase sign-in. */
export function persistSession(user: User): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  notify(user);
}

export function clearSession(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(USER_KEY);
  notify(null);
}

/**
 * Force-refresh the Firebase ID token and return it.
 *
 * Returns `null` when there is no signed-in user. The caller treats `null` as
 * "sign in again".
 */
export function refreshAccessToken(_basePath: string): Promise<string | null> {
  return getIdToken(true);
}

/** The current Firebase ID token, refreshing it if it is near expiry. */
export async function getAccessToken(): Promise<string | null> {
  return getIdToken(false);
}

// Wire Firebase auth state into the local store so a sign-out in another tab
// (or a Firebase password change that revokes sessions) propagates here.
// Only wire up once Firebase is configured; otherwise the app can still mount
// and show a configuration prompt instead of crashing on import.
if (isBrowser() && isFirebaseConfigured()) {
  onAuthStateChange((firebaseUser) => {
    if (!firebaseUser) {
      clearSession();
    }
    // On sign-in we don't yet have the Coraxis record; the tab that signed in
    // persists it via `persistSession` after `GET /auth/me`, and other tabs
    // reconcile on their next `api.auth.me()` check.
  });
}
