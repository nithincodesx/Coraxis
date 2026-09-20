/**
 * Animation preference.
 *
 * Controls motion across the whole app: the particle canvas, the drifting
 * ambient orbs, the panning grid, and the status pulses. Persisted the same way
 * as the theme — an attribute on `<html>` plus a blocking bootstrap script — so
 * the setting applies before first paint and cannot flash.
 *
 * Kept separate from `theme.ts` because the two are independent: a user may
 * want the light theme with motion, or the dark theme without it.
 */

export const ANIMATIONS_STORAGE_KEY = "coraxis.animations";

/** Motion is on unless the user turns it off. */
export const DEFAULT_ANIMATIONS = true;

type Listener = (enabled: boolean) => void;

const listeners = new Set<Listener>();

export function readAnimations(): boolean {
  if (typeof window === "undefined") return DEFAULT_ANIMATIONS;

  try {
    const stored = window.localStorage.getItem(ANIMATIONS_STORAGE_KEY);
    if (stored === "off") return false;
    if (stored === "on") return true;
  } catch {
    // Private mode: fall through to the default.
  }

  return DEFAULT_ANIMATIONS;
}

export function applyAnimations(enabled: boolean, { persist = true } = {}): void {
  if (typeof document === "undefined") return;

  document.documentElement.setAttribute("data-animations", enabled ? "on" : "off");

  if (persist) {
    try {
      window.localStorage.setItem(ANIMATIONS_STORAGE_KEY, enabled ? "on" : "off");
    } catch {
      // Failing to persist is not worth failing the toggle over.
    }
  }

  for (const listener of listeners) listener(enabled);
}

export function subscribeAnimations(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getCurrentAnimations(): boolean {
  if (typeof document === "undefined") return DEFAULT_ANIMATIONS;
  return document.documentElement.getAttribute("data-animations") !== "off";
}

/**
 * Runs before first paint. Mirrors the theme bootstrap: anything async here
 * reintroduces the flash it exists to prevent.
 */
export const ANIMATIONS_BOOTSTRAP_SCRIPT = `(function(){try{var v=localStorage.getItem('${ANIMATIONS_STORAGE_KEY}');document.documentElement.setAttribute('data-animations',v==='off'?'off':'on');}catch(e){document.documentElement.setAttribute('data-animations','on');}})();`;
