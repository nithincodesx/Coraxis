"use client";

/**
 * Past research sessions.
 *
 * An archive, not a card list: each session is a row with its title, status
 * and figures set in typography, separated by hairlines.
 *
 * Replaces `/api/history` and `/api/history/select`, which addressed runs by
 * their index in a JSON file. Indexes shift as runs are added or deleted, so
 * "load project 3" could open a different project than the one clicked. Runs
 * are addressed by id here, which cannot drift.
 */

import { RefreshCw, Trash2 } from "lucide-react";

import { EmptyState, Rule } from "./ui";
import { formatTimestamp, statusLabel } from "../lib/derive";
import type { Run, RunStatus } from "../lib/types";

interface Props {
  runs: Run[];
  selectedId: string | null;
  isLoading: boolean;
  onSelect: (runId: string) => void;
  onDelete: (runId: string) => void;
  onRefresh: () => void;
}

/** Status → colour. Only failure and success carry hue. */
function statusColour(status: RunStatus): string {
  switch (status) {
    case "succeeded":
      return "var(--success)";
    case "failed":
    case "timed_out":
      return "var(--danger)";
    case "running":
      return "var(--accent)";
    default:
      return "var(--text-faint)";
  }
}

export default function RunHistory({
  runs,
  selectedId,
  isLoading,
  onSelect,
  onDelete,
  onRefresh,
}: Props) {
  return (
    <div>
      <div className="flex items-center justify-between pb-3">
        <div>
          <p className="t-label">Archive</p>
          <h2 className="t-h2 mt-1">
            History <span className="t-meta">{runs.length}</span>
          </h2>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          aria-label="Refresh history"
          className="transition-opacity hover:opacity-70"
          style={{ color: "var(--text-muted)" }}
        >
          <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} />
        </button>
      </div>
      <Rule />

      {runs.length === 0 ? (
        <EmptyState
          title={isLoading ? "Loading…" : "No sessions yet"}
          body={isLoading ? undefined : "Completed research appears here."}
        />
      ) : (
        <div className="max-h-[460px] overflow-y-auto">
          {runs.map((run, i) => {
            const selected = run.id === selectedId;
            return (
              <div key={run.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(run.id)}
                  aria-current={selected ? "true" : undefined}
                  className="w-full py-3.5 text-left transition-opacity hover:opacity-80"
                  style={{ borderBottom: "1px solid var(--border-subtle)" }}
                >
                  <div className="flex items-baseline gap-3">
                    <span className="t-index shrink-0">{String(i + 1).padStart(2, "0")}</span>
                    <div className="min-w-0 flex-1 pr-6">
                      <p
                        className="line-clamp-2 text-[12px] font-medium leading-snug"
                        style={{ color: selected ? "var(--text)" : "var(--text-secondary)" }}
                      >
                        {run.query}
                      </p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span
                          className="flex items-center gap-1.5"
                          style={{ color: statusColour(run.status) }}
                        >
                          <span
                            className={`dot ${run.status === "running" ? "dot-active" : ""}`}
                            style={run.status !== "running" ? { background: statusColour(run.status) } : undefined}
                            aria-hidden
                          />
                          <span className="t-label" style={{ color: statusColour(run.status) }}>
                            {statusLabel(run.status)}
                          </span>
                        </span>
                        <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                          {formatTimestamp(run.created_at)}
                        </span>
                        <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                          {run.source_count}s · {run.claim_count}c
                        </span>
                      </div>
                    </div>
                  </div>
                </button>

                {/* Selected marker: a hairline rail, not a filled card */}
                {selected && (
                  <span
                    aria-hidden
                    className="absolute left-0 top-0 h-full w-[2px]"
                    style={{ background: "var(--accent)" }}
                  />
                )}

                <button
                  type="button"
                  onClick={() => onDelete(run.id)}
                  aria-label={`Delete ${run.query}`}
                  className="absolute right-0 top-3.5 opacity-0 transition-opacity hover:opacity-100 group-hover:opacity-60 focus-visible:opacity-100"
                  style={{ color: "var(--danger)" }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
