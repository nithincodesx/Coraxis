"use client";

import {
  ArrowUpRight,
  ChevronDown,
  Sparkles,
  FlaskConical,
  Search,
  BarChart3,
  FileText,
} from "lucide-react";

import type { Tab } from "../lib/nav";

/**
 * Landing hero — content only.
 *
 * The rounded frame and the navigation are supplied by `AppShell` and
 * `TopNavigation`, exactly as they are for every internal page. This file used
 * to own `.hl-frame` / `.hl-card` / `.hl-nav`, which is why the landing surface
 * and the app surface were built from two different shells.
 *
 * The composition itself is unchanged: same headline, subtitle, CTAs, floating
 * agent nodes, light streaks and bottom bar. Only the shell moved out.
 */

const NODES = [
  { icon: FlaskConical, name: "Researcher", tag: "01", pos: "hl-node-tl" },
  { icon: Search, name: "Searcher", tag: "02", pos: "hl-node-bl" },
  { icon: BarChart3, name: "Analyst", tag: "03", pos: "hl-node-tr" },
  { icon: FileText, name: "Writer", tag: "04", pos: "hl-node-br" },
];

export default function HeroContent({ onEnter }: { onEnter: (tab?: Tab) => void }) {
  return (
    <div className="hl-hero">
      {/* Hero-only flourish; the backdrop itself belongs to the shell. */}
      <div className="hl-streaks" aria-hidden>
        <span />
        <span />
        <span />
      </div>

      {/* Floating agent nodes */}
      {NODES.map((n) => (
        <div key={n.name} className={`hl-node ${n.pos}`}>
          <span className="hl-node-chip">
            <n.icon size={13} />
          </span>
          <span className="hl-node-meta">
            <span className="hl-node-name">{n.name}</span>
            <span className="hl-node-tag">{n.tag}</span>
          </span>
        </div>
      ))}

      {/* Hero core */}
      <main className="hl-center">
        <div className="hl-badge">
          <Sparkles size={11} />
          <span>Multi-agent research lab</span>
          <ArrowUpRight size={11} />
        </div>

        <h1 className="hl-title">
          One prompt to <span>Deep Research</span>
        </h1>

        <p className="hl-sub">
          Four agents decompose your question, crawl the web, cross-check every source, and hand
          back a cited report you can verify.
        </p>

        <div className="hl-ctas">
          <button className="hl-cta-dark" onClick={() => onEnter("workspace")}>
            Open Workspace <ArrowUpRight size={13} />
          </button>
          <button className="hl-cta-light" onClick={() => onEnter("teams")}>
            Discover Teams
          </button>
        </div>
      </main>

      {/* Bottom bar */}
      <footer className="hl-bottom">
        <button className="hl-scroll" onClick={() => onEnter()}>
          <span className="hl-scroll-orb">
            <ChevronDown size={13} />
          </span>
          01/01 · Enter the lab
        </button>
        <div className="hl-horizon">
          <span>Coraxis horizons</span>
          <div className="hl-horizon-bar">
            <span />
          </div>
        </div>
      </footer>
    </div>
  );
}
