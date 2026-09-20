/**
 * Theme selection and persistence.
 *
 * Dark is the default and the primary experience; light is a first-class
 * alternative rather than an inversion. The theme is expressed as a
 * `data-theme` attribute on `<html>`, which every colour token in
 * `globals.css` keys off.
 *
 * `THEME_BOOTSTRAP_SCRIPT` is injected into `<head>` as a blocking inline
 * script. It has to run before first paint: if the theme were applied from a
 * React effect instead, a light-mode user would get a flash of the dark
 * default on every navigation.
 */

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "coraxis.theme";

/** The default when nothing is stored. Dark is the product's primary face. */
export const DEFAULT_THEME: Theme = "dark";

type Listener = (theme: Theme) => void;

const listeners = new Set<Listener>();

export function isTheme(value: unknown): value is Theme {
  return value === "dark" || value === "light";
}

/** Read the persisted theme, falling back to the OS preference then the default. */
export function readTheme(): Theme {
  if (typeof window === "undefined") return DEFAULT_THEME;

  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (isTheme(stored)) return stored;
  } catch {
    // Private mode or a blocked storage partition: fall through to the OS.
  }

  if (window.matchMedia?.("(prefers-color-scheme: light)").matches) return "light";
  return DEFAULT_THEME;
}

/** Write the theme to the document and notify subscribers. */
export function applyTheme(theme: Theme, { persist = true } = {}): void {
  if (typeof document === "undefined") return;

  document.documentElement.setAttribute("data-theme", theme);

  if (persist) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Not being able to persist is not worth failing the toggle over.
    }
  }

  for (const listener of listeners) listener(theme);
}

/** Subscribe to theme changes. Returns an unsubscribe function. */
export function subscribeTheme(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getCurrentTheme(): Theme {
  if (typeof document === "undefined") return DEFAULT_THEME;
  const attr = document.documentElement.getAttribute("data-theme");
  return isTheme(attr) ? attr : DEFAULT_THEME;
}

/**
 * Runs before first paint to set `data-theme` from storage.
 *
 * Kept as a string so it can be inlined into the document head without
 * shipping a separate request — anything async here reintroduces the flash it
 * exists to prevent.
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var k='${THEME_STORAGE_KEY}';var s=localStorage.getItem(k);var t=(s==='light'||s==='dark')?s:(window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;
