/**
 * Derivations over a run's event stream.
 *
 * The old frontend asked the backend for a pre-computed `agent_states` map on
 * every poll. That put presentation logic in the API and made the two sides
 * impossible to evolve separately. The event stream is the raw material; agent
 * progress is derived here, in the view layer that actually renders it.
 */

import type { RunEvent, RunStatus, Source } from "./types";

export type AgentPhase = "pending" | "running" | "done" | "error";

export interface AgentProgress {
  slug: string;
  phase: AgentPhase;
  /** Fraction complete, 0..1. Coarse: agents report steps, not percentages. */
  progress: number;
  startedAt: number | null;
  finishedAt: number | null;
  elapsedSeconds: number;
  message: string;
}

/** The four pipeline roles, in execution order. */
export const PIPELINE_AGENTS = [
  { slug: "researcher", title: "Senior Researcher", icon: "🔬" },
  { slug: "web_searcher", title: "Search Specialist", icon: "🔍" },
  { slug: "analyst", title: "Synthesis Analyst", icon: "📊" },
  { slug: "summarizer", title: "Lead Report Writer", icon: "📝" },
] as const;

function timestampOf(event: RunEvent): number {
  const parsed = Date.parse(event.created_at);
  return Number.isNaN(parsed) ? Date.now() : parsed;
}

/**
 * Fold the event timeline into one progress record per agent.
 *
 * Handles arbitrary agent slugs, not just the four built-ins, because a team
 * run can name its own.
 */
export function deriveAgentProgress(events: RunEvent[]): Record<string, AgentProgress> {
  const progress: Record<string, AgentProgress> = {};

  const ensure = (slug: string): AgentProgress => {
    if (!progress[slug]) {
      progress[slug] = {
        slug,
        phase: "pending",
        progress: 0,
        startedAt: null,
        finishedAt: null,
        elapsedSeconds: 0,
        message: "",
      };
    }
    return progress[slug];
  };

  for (const slug of PIPELINE_AGENTS.map((agent) => agent.slug)) ensure(slug);

  for (const event of events) {
    if (!event.agent) continue;
    const record = ensure(event.agent);
    const at = timestampOf(event);

    switch (event.type) {
      case "agent.started":
        record.phase = "running";
        record.startedAt = at;
        record.progress = Math.max(record.progress, 0.1);
        record.message = event.message;
        break;
      case "agent.progress":
        if (record.phase !== "error") record.phase = "running";
        if (record.startedAt === null) record.startedAt = at;
        // Nudge forward without ever reaching 1 — only completion does that.
        record.progress = Math.min(0.9, Math.max(record.progress, 0.1) + 0.12);
        record.message = event.message;
        break;
      case "agent.completed":
        record.phase = "done";
        record.progress = 1;
        record.finishedAt = at;
        record.message = event.message;
        break;
      case "agent.failed":
        record.phase = "error";
        record.finishedAt = at;
        record.message = event.message;
        break;
      default:
        break;
    }

    if (record.startedAt !== null) {
      const end = record.finishedAt ?? at;
      record.elapsedSeconds = Math.max(0, (end - record.startedAt) / 1000);
    }
  }

  return progress;
}

/** The most recent event that describes what is happening right now. */
export function latestActivity(events: RunEvent[]): RunEvent | null {
  return events.length ? events[events.length - 1] : null;
}

/** Agent-to-agent messages, extracted from the unified stream. */
export interface AgentMessage {
  from: string;
  to: string;
  message: string;
  at: string;
}

export function extractAgentMessages(events: RunEvent[]): AgentMessage[] {
  const messages: AgentMessage[] = [];
  for (const event of events) {
    if (event.type !== "agent.message") continue;
    const payload = event.payload as Record<string, unknown>;
    messages.push({
      from: String(payload.from_agent ?? event.agent ?? "system"),
      to: String(payload.to_agent ?? "all"),
      message: String(payload.message ?? event.message ?? ""),
      at: event.created_at,
    });
  }
  return messages;
}

/** Sources discovered so far, taken from `source.added` events. */
export function extractSources(events: RunEvent[]): Source[] {
  const seen = new Map<string, Source>();

  for (const event of events) {
    if (event.type !== "source.added") continue;
    const payload = event.payload as Record<string, unknown>;
    const url = String(payload.url ?? "");
    if (!url || seen.has(url)) continue;

    const relevance = Number(payload.relevance ?? 0);
    seen.set(url, {
      id: String(payload.id ?? url),
      url,
      title: String(payload.title ?? url),
      relevance,
      relevance_pct: Math.round(Math.max(0, Math.min(1, relevance)) * 100),
      snippet: String(payload.snippet ?? ""),
      word_count: Number(payload.word_count ?? 0),
      fetch_success: Boolean(payload.fetch_success ?? false),
    });
  }

  return [...seen.values()].sort((a, b) => b.relevance - a.relevance);
}

// ─── Formatting ──────────────────────────────────────────────────────

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${remainder}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatClock(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatTimestamp(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Tailwind classes for a status pill, kept in one place so they stay in step. */
export function statusBadgeClass(status: RunStatus): string {
  switch (status) {
    case "succeeded":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "failed":
      return "bg-rose-50 text-rose-700 border-rose-200";
    case "cancelled":
      return "bg-slate-100 text-slate-600 border-slate-200";
    case "timed_out":
      return "bg-amber-50 text-amber-700 border-amber-200";
    case "running":
      return "bg-indigo-50 text-indigo-700 border-indigo-200";
    default:
      return "bg-slate-100 text-slate-500 border-slate-200";
  }
}

/** A short, human label for a run status. */
export function statusLabel(status: RunStatus): string {
  switch (status) {
    case "succeeded":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    case "timed_out":
      return "Timed out";
    case "running":
      return "Running";
    default:
      return "Queued";
  }
}
