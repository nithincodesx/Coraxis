"use client";

/**
 * React view of the animation preference.
 *
 * Same shape as `useTheme`: seeded with the default and synchronised from the
 * document in an effect, because the server always renders the default.
 */

import { useCallback, useEffect, useState } from "react";

import {
  DEFAULT_ANIMATIONS,
  applyAnimations,
  getCurrentAnimations,
  subscribeAnimations,
} from "../lib/animations";

export interface UseAnimationsResult {
  animationsEnabled: boolean;
  setAnimations: (enabled: boolean) => void;
  isReady: boolean;
}

export function useAnimations(): UseAnimationsResult {
  const [animationsEnabled, setState] = useState<boolean>(DEFAULT_ANIMATIONS);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    // Adopts the value the bootstrap script already wrote to the document.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(getCurrentAnimations());
    setIsReady(true);
    return subscribeAnimations(setState);
  }, []);

  const setAnimations = useCallback((enabled: boolean) => {
    applyAnimations(enabled);
    setState(enabled);
  }, []);

  return { animationsEnabled, setAnimations, isReady };
}
