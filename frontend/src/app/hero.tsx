"use client";

import React from "react";
import {
  ArrowUpRight,
  ChevronDown,
  Sparkles,
  FlaskConical,
  Search,
  BarChart3,
  FileText,
  User,
  Zap,
} from "lucide-react";
import "./hero.css";

export type HeroTab = "agents" | "workspace" | "teams" | "settings";

/**
 * Coraxis Landing — dark inset-card hero (DeFi reference style).
 * Shown on app load; every control enters the workspace.
 */

const NODES = [
  { icon: FlaskConical, name: "Researcher", tag: "01", pos: "hl-node-tl" },
  { icon: Search, name: "Searcher", tag: "02", pos: "hl-node-bl" },
  { icon: BarChart3, name: "Analyst", tag: "03", pos: "hl-node-tr" },
  { icon: FileText, name: "Writer", tag: "04", pos: "hl-node-br" },
];

export default function HeroLanding({ onEnter }: { onEnter: (tab?: HeroTab) => void }) {
  return (
    <div className="hl-frame">
      <div className="hl-card">
        {/* Ambient top glow + falling light streaks */}
        <div className="hl-card-glow" />
        <div className="hl-streaks" aria-hidden>
          <span /><span /><span />
        </div>

        {/* ── Nav: logo · centered pill · account ── */}
        <header className="hl-nav">
          <button className="hl-logo" onClick={() => onEnter()} title="Enter Coraxis">
            <img src="/brand_sigil.jpg" alt="Coraxis" />
          </button>

          <nav className="hl-navpill">
            <button onClick={() => onEnter("agents")}>Overview</button>
            <button onClick={() => onEnter("workspace")}>Research</button>
            <button onClick={() => onEnter("teams")}>AI Teams</button>
            <button onClick={() => onEnter("settings")}>Settings</button>
            <span className="hl-navpill-divider" />
            <button className="hl-nav-cta" onClick={() => onEnter("teams")}>
              Build a Team <ArrowUpRight size={11} />
            </button>
            <button className="hl-nav-orb" onClick={() => onEnter("settings")} title="API Settings">
              <Zap size={12} />
            </button>
          </nav>

          <button className="hl-account" onClick={() => onEnter()}>
            <span className="hl-account-icon"><User size={13} /></span>
            Enter Workspace
          </button>
        </header>

        {/* ── Floating agent nodes ── */}
        {NODES.map((n) => (
          <div key={n.name} className={`hl-node ${n.pos}`}>
            <span className="hl-node-chip"><n.icon size={13} /></span>
            <span className="hl-node-meta">
              <span className="hl-node-name">{n.name}</span>
              <span className="hl-node-tag">{n.tag}</span>
            </span>
          </div>
        ))}

        {/* ── Hero core ── */}
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
            Four agents decompose your question, crawl the web, cross-check every
            source, and hand back a cited report you can verify.
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

        {/* ── Bottom bar ── */}
        <footer className="hl-bottom">
          <button className="hl-scroll" onClick={() => onEnter()}>
            <span className="hl-scroll-orb"><ChevronDown size={13} /></span>
            01/01 · Enter the lab
          </button>
          <div className="hl-horizon">
            <span>Coraxis horizons</span>
            <div className="hl-horizon-bar"><span /></div>
          </div>
        </footer>
      </div>
    </div>
  );
}
