"use client";

/**
 * The research workspace: submit a query, watch it run, read the result.
 *
 * State comes from two places and they are not duplicated. The run's *record*
 * (status, stats, stored report, evidence) is fetched from the API and
 * refetched when the stream reports a terminal event. The run's *progress* is
 * derived from the live event stream. Nothing is polled on a timer.
 *
 * Layout is a two-column composition — the research surface takes the measure,
 * the archive and run metadata sit in a narrower rail — rather than a uniform
 * grid of equal cards.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Loader2, Square } from "lucide-react";

import AgentProgressGrid from "./AgentProgressGrid";
import EventFeed from "./EventFeed";
import ReportPanel from "./ReportPanel";
import RunHistory from "./RunHistory";
import { Button, Chip, MetaRow, PageHeader, Rule, Section, Select } from "./ui";

import { ApiError, api } from "../lib/api";
import { useAsyncData } from "../hooks/useAsyncData";
import { useRunStream } from "../hooks/useRunStream";
import {
  deriveAgentProgress,
  extractSources,
  formatTimestamp,
  statusLabel,
} from "../lib/derive";
import { isTerminal } from "../lib/types";
import type { Page, Run, RunDetail, Team } from "../lib/types";

interface Props {
  teams: Team[];
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
}

export default function WorkspaceTab({ teams, onError, onSuccess }: Props) {
  const [query, setQuery] = useState("");
  const [teamId, setTeamId] = useState<string>("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [clearedFrom, setClearedFrom] = useState(0);

  const history = useAsyncData<Page<Run>>(() => api.runs.list({ limit: 50 }));
  const detail = useAsyncData<RunDetail | null>(
    () => (activeRunId ? api.runs.get(activeRunId) : Promise.resolve(null)),
    { enabled: Boolean(activeRunId), refreshKey: activeRunId ?? "" },
  );

  const stream = useRunStream(activeRunId);
  const inputRef = useRef<HTMLInputElement>(null);

  const visibleEvents = useMemo(
    () => stream.events.filter((event) => event.seq > clearedFrom),
    [stream.events, clearedFrom],
  );

  const agentProgress = useMemo(() => deriveAgentProgress(visibleEvents), [visibleEvents]);
  const liveSources = useMemo(() => extractSources(visibleEvents), [visibleEvents]);

  const run = detail.data;
  const isLive = run ? !isTerminal(run.status) : false;

  // When the stream reports a terminal state, pull the run record so the stored
  // report and evidence replace the live view.
  useEffect(() => {
    const last = visibleEvents[visibleEvents.length - 1];
    if (!last) return;
    const terminal = ["run.succeeded", "run.failed", "run.cancelled", "run.timed_out"];
    if (terminal.includes(last.type)) {
      void detail.refetch();
      void history.refetch();
      if (last.type === "run.succeeded") onSuccess("Research complete.");
      else if (last.type === "run.failed") onError(last.message || "The run failed.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleEvents.length]);

  const submit = async () => {
    const trimmed = query.trim();
    if (trimmed.split(/\s+/).length < 2) {
      onError("Give the query at least two words so the agents have something to work with.");
      return;
    }

    try {
      const accepted = await api.runs.submit({ query: trimmed, team_id: teamId || null });
      setClearedFrom(0);
      setActiveRunId(accepted.run_id);
      onSuccess("Run queued.");
      void history.refetch();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not start the run.");
    }
  };

  const cancel = async () => {
    if (!activeRunId) return;
    try {
      await api.runs.cancel(activeRunId);
      onSuccess("Cancellation requested — agents stop at the next step boundary.");
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not cancel the run.");
    }
  };

  const selectRun = (runId: string) => {
    setClearedFrom(0);
    setActiveRunId(runId);
  };

  const removeRun = async (runId: string) => {
    try {
      await api.runs.remove(runId);
      if (runId === activeRunId) setActiveRunId(null);
      await history.refetch();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not delete the run.");
    }
  };

  return (
    <div className="fade-in">
      <PageHeader
        label="Research Workspace"
        title={run ? "Active Session" : "New Session"}
        description={
          run
            ? undefined
            : "Ask a question and four specialised agents will search, cross-check and synthesise a cited report."
        }
        actions={
          run ? (
            <div className="flex items-center gap-2">
              <Chip tone={run.status === "succeeded" ? "success" : run.status === "failed" ? "danger" : "neutral"}>
                {statusLabel(run.status)}
              </Chip>
              {isLive && (
                <Button size="sm" variant="ghost" icon={<Square size={11} />} onClick={() => void cancel()}>
                  Cancel
                </Button>
              )}
            </div>
          ) : undefined
        }
      />

      {/* ── Query input ───────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void submit()}
            placeholder="Ask any research topic or question…"
            aria-label="Research query"
            className="input"
            style={{ padding: "0.875rem 1rem", fontSize: "0.875rem", borderRadius: "var(--r-full)" }}
          />
        </div>

        {teams.length > 0 && (
          <Select
            value={teamId}
            onChange={(event) => setTeamId(event.target.value)}
            aria-label="Team"
            title="Run a saved team instead of the default pipeline"
            style={{ width: "auto", borderRadius: "var(--r-full)", minWidth: 150 }}
          >
            <option value="">Default pipeline</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </Select>
        )}

        <Button
          variant="primary"
          onClick={() => void submit()}
          disabled={!query.trim()}
          icon={<ArrowRight size={14} />}
        >
          Run
        </Button>
      </div>

      {/* ── Active run ────────────────────────────────────────────────── */}
      <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex flex-col gap-10">
          <Section>
            <AgentProgressGrid progress={agentProgress} isLive={isLive} />
          </Section>

          <Section label="Stream" title="Live Execution">
            <EventFeed
              events={visibleEvents}
              streamStatus={stream.status}
              onClear={() => setClearedFrom(stream.lastSeq)}
            />
            {stream.error && (
              <p className="t-meta mt-3" style={{ color: "var(--warning)" }}>
                {stream.error}
              </p>
            )}
          </Section>

          <Section label="Output" title="Report">
            <ReportPanel run={run ?? null} liveSources={liveSources} onError={onError} />
          </Section>
        </div>

        {/* Rail */}
        <aside className="flex flex-col gap-10">
          <RunHistory
            runs={history.data?.items ?? []}
            selectedId={activeRunId}
            isLoading={history.isLoading}
            onSelect={selectRun}
            onDelete={(id) => void removeRun(id)}
            onRefresh={() => void history.refetch()}
          />

          {run && (
            <div>
              <p className="t-label pb-3">Session</p>
              <Rule />
              <div className="pt-3">
                <MetaRow label="trigger" value={run.trigger} />
                <MetaRow label="started" value={run.started_at ? formatTimestamp(run.started_at) : "—"} />
                <MetaRow label="finished" value={run.finished_at ? formatTimestamp(run.finished_at) : "—"} />
                <MetaRow label="runtime" value={`${Math.round(run.runtime_seconds)}s`} />
                <MetaRow label="sources" value={String(run.source_count)} />
                <MetaRow label="claims" value={String(run.claim_count)} />
              </div>

              {run.error && (
                <>
                  <Rule className="my-4" />
                  <p
                    className="text-[11.5px] leading-relaxed"
                    style={{ color: "var(--danger)", fontFamily: "var(--font-mono)" }}
                  >
                    {run.error}
                  </p>
                </>
              )}
            </div>
          )}

          {detail.isLoading && activeRunId && (
            <span className="flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" style={{ color: "var(--text-faint)" }} />
              <span className="t-meta">Loading session…</span>
            </span>
          )}
        </aside>
      </div>
    </div>
  );
}
