"use client";

/**
 * The one top navigation.
 *
 * Used by every surface, including the landing hero. There is deliberately no
 * hero-specific variant: the hero previously had its own `.hl-nav` /
 * `.hl-navpill` markup with different geometry, which is what made the two
 * halves of the product look like separate applications.
 *
 * The hero's extra actions ("Build a Team", the settings orb) were dropped
 * rather than special-cased — "Build a Team" is the AI Teams tab, which is
 * already in the capsule, and the settings orb duplicated the Settings tab.
 * Keeping them would have meant two navigation geometries again.
 *
 * The user block and sign-out are optional so the same component renders the
 * sign-in screen, where there is no session yet.
 */

import { LogOut } from "lucide-react";

import ThemeToggle from "./ThemeToggle";
import { IconButton } from "./ui";
import type { Tab } from "../lib/nav";

const NAV: Array<{ tab: Tab; label: string }> = [
  { tab: "agents", label: "Overview" },
  { tab: "workspace", label: "Research" },
  { tab: "teams", label: "AI Teams" },
  { tab: "settings", label: "Settings" },
];

interface Props {
  /** null while the landing hero is showing — nothing is "current" there. */
  activeTab: Tab | null;
  onNavigate: (tab: Tab) => void;
  onHome: () => void;
  /**
   * True before sign-in. The capsule still renders so the navigation geometry
   * is identical on every surface, but the tabs are genuinely disabled rather
   * than inert buttons that silently do nothing.
   */
  tabsDisabled?: boolean;
  userLabel?: string;
  userEmail?: string;
  onSignOut?: () => void;
}

export default function TopNavigation({
  activeTab,
  onNavigate,
  onHome,
  tabsDisabled = false,
  userLabel,
  userEmail,
  onSignOut,
}: Props) {
  return (
    <header className="app-nav">
      <nav className="glass app-nav-pill">
        <button
          type="button"
          onClick={onHome}
          className="font-display hidden shrink-0 rounded-full px-2 py-1 text-[12px] font-bold tracking-[0.18em] transition-opacity hover:opacity-70 sm:block"
          title="Coraxis"
        >
          CORAXIS
        </button>

        <div className="flex items-center gap-0.5">
          {NAV.map((item) => {
            const active = activeTab === item.tab;
            return (
              <button
                key={item.tab}
                type="button"
                onClick={() => onNavigate(item.tab)}
                disabled={tabsDisabled}
                aria-current={active ? "page" : undefined}
                data-tab={item.tab}
                className="font-display whitespace-nowrap rounded-full px-2 py-1.5 text-[11px] font-semibold transition-all disabled:cursor-not-allowed sm:px-3 sm:text-[11.5px]"
                style={{
                  background: active ? "var(--accent)" : "transparent",
                  color: active ? "var(--accent-contrast)" : "var(--text-secondary)",
                  opacity: tabsDisabled ? 0.4 : 1,
                }}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <ThemeToggle compact />
          {userLabel !== undefined && (
            <>
              <div className="hidden h-4 w-px lg:block" style={{ background: "var(--border)" }} />
              <span className="t-meta hidden max-w-[130px] truncate lg:block" title={userEmail}>
                {userLabel}
              </span>
            </>
          )}
          {onSignOut && (
            <IconButton label="Sign out" icon={<LogOut size={13} />} onClick={onSignOut} />
          )}
        </div>
      </nav>
    </header>
  );
}
