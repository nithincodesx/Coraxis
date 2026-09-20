"use client";

/**
 * Theme toggle.
 *
 * A two-position segmented control rather than a single cycling button: with
 * only two themes, showing both states makes the current one unambiguous and
 * the target reachable in one click instead of a guess.
 */

import { Moon, Sun } from "lucide-react";

import { useTheme } from "../hooks/useTheme";
import type { Theme } from "../lib/theme";

export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme, isReady } = useTheme();

  const options: Array<{ value: Theme; label: string; icon: typeof Sun }> = [
    { value: "dark", label: "Dark", icon: Moon },
    { value: "light", label: "Light", icon: Sun },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex items-center gap-0.5 rounded-full p-0.5"
      style={{
        border: "1px solid var(--border)",
        background: "var(--surface-hover)",
        // Avoid a visible flip of the active pill before storage is read.
        opacity: isReady ? 1 : 0.6,
        transition: "opacity var(--dur) var(--ease)",
      }}
    >
      {options.map((option) => {
        const Icon = option.icon;
        const active = theme === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${option.label} theme`}
            title={`${option.label} theme`}
            onClick={() => setTheme(option.value)}
            className="flex items-center justify-center rounded-full transition-all"
            style={{
              width: compact ? 24 : 28,
              height: compact ? 24 : 26,
              background: active ? "var(--accent)" : "transparent",
              color: active ? "var(--accent-contrast)" : "var(--text-muted)",
              transition: "background-color var(--dur) var(--ease), color var(--dur) var(--ease)",
            }}
          >
            <Icon size={compact ? 12 : 13} />
          </button>
        );
      })}
    </div>
  );
}
