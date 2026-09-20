/**
 * Navigation model.
 *
 * The tab union lived in `hero.tsx` and `page.tsx` imported it from there,
 * which is backwards — the shell should not depend on a page. It lives here so
 * the shell, the navigation and the hero all agree on one definition.
 */

export type Tab = "agents" | "workspace" | "teams" | "settings";

export const TABS: readonly Tab[] = ["agents", "workspace", "teams", "settings"];

/** The tab a visitor lands on after leaving the hero. */
export const DEFAULT_TAB: Tab = "agents";
