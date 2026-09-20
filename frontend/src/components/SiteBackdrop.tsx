"use client";

/**
 * Site-wide animated background.
 *
 * Fixed behind every page — the app shell, the sign-in gate, the workspace.
 * The hero keeps its own copy inside the inset card, because that surface is
 * clipped to a rounded rectangle and needs the field drawn within its bounds.
 * The two are mutually exclusive (the hero covers the viewport), so only one
 * canvas is ever running.
 *
 * Sits at `z-index: 0` with `pointer-events: none`, so it never intercepts a
 * click and never needs a stacking fix from the pages above it.
 */

import { useAnimations } from "../hooks/useAnimations";
import HeroBackdrop from "./HeroBackdrop";

export default function SiteBackdrop({ variant = "app" }: { variant?: "app" | "auth" }) {
  const { animationsEnabled } = useAnimations();

  // Fewer particles behind the app than behind the hero: the working surfaces
  // carry dense text, so the field has to stay further out of the way.
  const count = variant === "auth" ? 44 : 30;

  return (
    <div className="sb-root" aria-hidden>
      <span className="sb-orb sb-orb-1" />
      <span className="sb-orb sb-orb-2" />
      <span className="sb-orb sb-orb-3" />
      <span className="sb-grid" />
      <HeroBackdrop enabled={animationsEnabled} count={count} />
    </div>
  );
}
