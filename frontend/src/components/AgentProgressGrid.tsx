"use client";

/**
 * Agent execution state.
 *
 * Rendered as a status list rather than four progress-bar cards: an index, the
 * agent's name, what it is doing right now, and a single status indicator. The
 * brief called for agents to feel active and intelligent — that comes from
 * showing the *current activity* in words, which the old progress bars never
 * did, rather than from more chrome.
 *
 * `deriveAgentProgress` does the folding from the event stream; this component
 * only renders.
 */

import { PIPELINE_AGENTS, type AgentProgress } from "../lib/derive";
import { Index, Rule } from "./ui";

interface Props {
  progress: Record<string, AgentProgress>;
  isLive: boolean;
}

/** Status vocabulary, ordered from idle to failed. */
function statusOf(phase: AgentProgress["phase"]): {
  label: string;
  tone: "neutral" | "success" | "warning" | "danger" | "info";
  pulse: boolean;
} {
  switch (phase) {
    case "running":
      return { label: "Active", tone: "info", pulse: true };
    case "done":
      return { label: "Complete", tone: "success", pulse: false };
    case "error":
      return { label: "Failed", tone: "danger", pulse: false };
    default:
      return { label: "Standby", tone: "neutral", pulse: false };
  }
}

const TONE_COLOUR: Record<string, string> = {
  neutral: "var(--text-faint)",
  success: "var(--success)",
  warning: "var(--warning)",
  danger: "var(--danger)",
  info: "var(--accent)",
};

export default function AgentProgressGrid({ progress, isLive }: Props) {
  const known = new Set<string>(PIPELINE_AGENTS.map((agent) => agent.slug));
  const extra = Object.keys(progress)
    .filter((slug) => !known.has(slug))
    .sort();

  const rows = [
    ...PIPELINE_AGENTS.map((agent) => ({ slug: agent.slug, title: agent.title })),
    ...extra.map((slug) => ({ slug, title: slug })),
  ];

  return (
    <div>
      <div className="flex items-center justify-between pb-3">
        <div>
          <p className="t-label">Pipeline</p>
          <h2 className="t-h2 mt-1">{rows.length} agents</h2>
        </div>
        {isLive && (
          <span className="flex items-center gap-2">
            <span className="dot dot-active" aria-hidden />
            <span className="t-meta" style={{ color: "var(--text-secondary)" }}>
              executing
            </span>
          </span>
        )}
      </div>
      <Rule />

      <div className="fade-in-stagger">
        {rows.map((row, i) => {
          const state: AgentProgress = progress[row.slug] ?? {
            slug: row.slug,
            phase: "pending",
            progress: 0,
            startedAt: null,
            finishedAt: null,
            elapsedSeconds: 0,
            message: "",
          };
          const status = statusOf(state.phase);
          const colour = TONE_COLOUR[status.tone];

          return (
            <div key={row.slug}>
              <div className="flex items-center gap-4 py-3.5 sm:gap-6">
                <div className="w-6 shrink-0">
                  <Index n={i + 1} />
                </div>

                <div className="min-w-0 flex-1">
                  <h3
                    className="t-h3 transition-colors"
                    style={{ color: state.phase === "pending" ? "var(--text-muted)" : "var(--text)" }}
                  >
                    {row.title}
                  </h3>
                  <p
                    className="t-meta mt-1 truncate"
                    style={{ color: state.message ? "var(--text-muted)" : "var(--text-faint)" }}
                    title={state.message}
                  >
                    {state.message ||
                      (state.phase === "pending" ? "Awaiting upstream results" : "—")}
                  </p>
                </div>

                {/* Elapsed, only once there is something to report */}
                {state.elapsedSeconds > 0 && (
                  <span className="t-meta hidden shrink-0 tabular-nums sm:block">
                    {Math.round(state.elapsedSeconds)}s
                  </span>
                )}

                <div className="flex w-[92px] shrink-0 items-center justify-end gap-2">
                  <span className={`dot ${status.pulse ? "dot-active" : ""}`} style={!status.pulse ? { background: colour } : undefined} aria-hidden />
                  <span
                    className="t-label"
                    style={{ color: colour, letterSpacing: "0.1em" }}
                  >
                    {status.label}
                  </span>
                </div>
              </div>
              {i < rows.length - 1 && <Rule />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
