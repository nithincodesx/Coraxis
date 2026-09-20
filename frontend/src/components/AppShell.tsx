"use client";

/**
 * The one application shell.
 *
 * Every surface renders inside this — the landing hero, the workspace, the
 * sign-in gate — so the rounded frame, the viewport inset, the clipping and
 * the backdrop are defined exactly once.
 *
 * It previously existed only as `.hl-frame` / `.hl-card` in the hero, while the
 * internal pages had no frame at all and floated a nav over a full-bleed
 * background. Two different shells for one product. The frame now lives here
 * and the hero uses it like any other page.
 *
 * Structure:
 *
 *   .app-frame    fixed viewport inset + page background
 *   .app-surface  the rounded, clipped application surface
 *   .app-stack    a stable column: navigation on top, content below
 *
 * `app-surface` is `overflow: hidden`, so the animated backdrop is clipped by
 * the rounded corners instead of bleeding into the browser's square edges.
 */

import type { ReactNode } from "react";

import SiteBackdrop from "./SiteBackdrop";

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-frame">
      <div className="app-surface">
        {/* Backdrop lives inside the surface so the corner radius clips it. */}
        <SiteBackdrop />
        <div className="app-stack">{children}</div>
      </div>
    </div>
  );
}
