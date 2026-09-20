import type { Metadata } from "next";
import localFont from "next/font/local";

import { ANIMATIONS_BOOTSTRAP_SCRIPT } from "../lib/animations";
import { THEME_BOOTSTRAP_SCRIPT } from "../lib/theme";
import "./globals.css";

/**
 * Three families, matching the landing page exactly: Inter for display and
 * body, Space Grotesk for UI labels, JetBrains Mono for technical metadata.
 *
 * Self-hosted rather than fetched from Google at build time. `next/font/google`
 * could not reach fonts.googleapis.com from this environment and silently fell
 * back to system fonts — which meant Space Grotesk and JetBrains Mono, both
 * load-bearing for the design, were not actually rendering. The files are the
 * latin subsets of the variable fonts, so one file covers the whole weight
 * range, and serving them locally removes a third-party request from the
 * critical path.
 */
const inter = localFont({
  src: "./fonts/Inter.woff2",
  weight: "300 600",
  variable: "--font-inter",
  display: "swap",
  fallback: ["-apple-system", "BlinkMacSystemFont", "sans-serif"],
});

const spaceGrotesk = localFont({
  src: "./fonts/SpaceGrotesk.woff2",
  weight: "500 700",
  variable: "--font-space-grotesk",
  display: "swap",
  fallback: ["Inter", "sans-serif"],
});

const jetbrainsMono = localFont({
  src: "./fonts/JetBrainsMono.woff2",
  weight: "400 500",
  variable: "--font-jetbrains-mono",
  display: "swap",
  fallback: ["ui-monospace", "monospace"],
});

export const metadata: Metadata = {
  title: "Coraxis — Autonomous Multi-Agent Research Laboratory",
  description:
    "Watch four specialised agents research a topic live: search, cross-check sources, reason through findings, and produce a structured, cited report.",
  keywords: [
    "AI agents",
    "CrewAI",
    "multi-agent research",
    "Groq",
    "deep research",
    "Coraxis",
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `data-theme` is set by the bootstrap script before first paint. Dark is
    // the default, so the attribute is absent on a first dark-mode visit and
    // the :root tokens apply unchanged.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <head>
        {/* Both run before first paint so neither the theme nor the motion
            setting can flash the default. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: ANIMATIONS_BOOTSTRAP_SCRIPT }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
