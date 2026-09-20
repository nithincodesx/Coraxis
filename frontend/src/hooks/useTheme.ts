"use client";

/**
 * React view of the theme store.
 *
 * State is seeded with the default and synchronised from the document in an
 * effect. Reading `data-theme` in a lazy initialiser would be more direct but
 * would desynchronise server and client markup for a light-mode user — the
 * server always renders the default. The bootstrap script has already painted
 * the correct theme by then, so only this component's own icon settles one
 * tick late.
 */

import { useCallback, useEffect, useState } from "react";

import {
  DEFAULT_THEME,
  applyTheme,
  getCurrentTheme,
  subscribeTheme,
  type Theme,
} from "../lib/theme";

export interface UseThemeResult {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
  /** True once the stored value has been read, so the toggle can avoid flicker. */
  isReady: boolean;
}

export function useTheme(): UseThemeResult {
  const [theme, setThemeState] = useState<Theme>(DEFAULT_THEME);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    // Reading the theme and subscribing to changes is exactly the
    // "synchronise with an external system" case effects exist for. The
    // setState here adopts the value the bootstrap script already applied to
    // the document; without it the toggle would render the default until the
    // first user interaction.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThemeState(getCurrentTheme());
    setIsReady(true);
    return subscribeTheme(setThemeState);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    applyTheme(next);
    setThemeState(next);
  }, []);

  const toggle = useCallback(() => {
    setTheme(getCurrentTheme() === "dark" ? "light" : "dark");
  }, [setTheme]);

  return { theme, setTheme, toggle, isReady };
}
