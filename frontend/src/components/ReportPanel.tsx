"use client";

/**
 * The finished report, its evidence, and the run's headline numbers.
 *
 * Styled as a research document rather than a dashboard panel: the report body
 * gets a readable measure and document typography, sources read as a
 * reference list, and claims carry their confidence inline.
 *
 * Citations render from the markdown the server produced, which already holds
 * the stable `[^n]` numbers. The client renumbers nothing — doing so is what
 * made saved reports drift from their source list previously.
 */

import { useState } from "react";
import { Download, ExternalLink, FileText, Loader2 } from "lucide-react";

import { Button, EmptyState, Rule, Stat } from "./ui";
import { api } from "../lib/api";
import type { Claim, RunDetail, Source } from "../lib/types";

interface Props {
  run: RunDetail | null;
  liveSources: Source[];
  onError: (message: string) => void;
}

type Panel = "report" | "sources" | "claims";

export default function ReportPanel({ run, liveSources, onError }: Props) {
  const [panel, setPanel] = useState<Panel>("report");
  const [downloading, setDownloading] = useState(false);

  const sources = run?.sources?.length ? run.sources : liveSources;
  const claims: Claim[] = run?.claims ?? [];
  const markdown = run?.report_markdown ?? "";
  const stats = run?.stats;

  const download = async () => {
    if (!run) return;
    setDownloading(true);
    try {
      const text = await api.runs.reportMarkdown(run.id);
      const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `coraxis-${run.id.slice(0, 8)}.md`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  const tabs: Array<{ key: Panel; label: string; count?: number }> = [
    { key: "report", label: "Report" },
    { key: "sources", label: "Sources", count: sources.length },
    { key: "claims", label: "Claims", count: claims.length },
  ];

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
        <div className="flex items-center gap-0.5">
          {tabs.map((tab) => {
            const active = panel === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setPanel(tab.key)}
                aria-pressed={active}
                className="font-display rounded-full px-3 py-1.5 text-[11.5px] font-semibold transition-all"
                style={{
                  background: active ? "var(--accent)" : "transparent",
                  color: active ? "var(--accent-contrast)" : "var(--text-muted)",
                }}
              >
                {tab.label}
                {tab.count !== undefined && (
                  <span style={{ opacity: 0.55 }}> {tab.count}</span>
                )}
              </button>
            );
          })}
        </div>

        {markdown && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void download()}
            disabled={downloading}
            icon={
              downloading ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Download size={12} />
              )
            }
          >
            {downloading ? "Preparing" : "Download"}
          </Button>
        )}
      </div>
      <Rule />

      {/* Run figures */}
      {stats && (stats.total_sources > 0 || stats.total_claims > 0) && (
        <>
          <div className="grid grid-cols-2 gap-6 py-5 sm:grid-cols-4">
            <Stat label="Sources" value={String(stats.total_sources)} />
            <Stat label="Claims" value={String(stats.total_claims)} />
            <Stat label="Avg confidence" value={`${Math.round(stats.avg_confidence * 100)}%`} />
            <Stat label="Runtime" value={`${Math.round(stats.runtime_seconds)}s`} />
          </div>
          <Rule />
        </>
      )}

      {/* ── Report ───────────────────────────────────────────────────── */}
      {panel === "report" && (
        <div className="max-h-[560px] overflow-y-auto py-6 pr-2">
          {markdown ? (
            <article className="mx-auto max-w-[68ch]">
              <pre
                className="whitespace-pre-wrap"
                style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: "0.875rem",
                  lineHeight: 1.8,
                  color: "var(--text-secondary)",
                }}
              >
                {markdown}
              </pre>
            </article>
          ) : (
            <EmptyState
              icon={<FileText size={20} />}
              title="No report yet"
              body="The report appears here once the pipeline finishes."
            />
          )}
        </div>
      )}

      {/* ── Sources ──────────────────────────────────────────────────── */}
      {panel === "sources" && (
        <div className="max-h-[560px] overflow-y-auto">
          {sources.length === 0 ? (
            <EmptyState
              icon={<ExternalLink size={20} />}
              title="No sources yet"
              body="Sources appear as the search agent discovers them."
            />
          ) : (
            sources.map((source, i) => (
              <a
                key={source.id}
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                className="group block py-3.5 transition-opacity hover:opacity-80"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <div className="flex items-baseline gap-3">
                  <span className="t-index shrink-0">{String(i + 1).padStart(2, "0")}</span>
                  <div className="min-w-0 flex-1">
                    <p
                      className="text-[12.5px] font-medium leading-snug"
                      style={{ color: "var(--text)" }}
                    >
                      {source.title || source.url}
                    </p>
                    <p className="t-meta mt-1 truncate" style={{ color: "var(--text-faint)" }}>
                      {source.url}
                    </p>
                    {source.snippet && (
                      <p
                        className="mt-2 line-clamp-2 text-[11.5px] leading-relaxed"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {source.snippet}
                      </p>
                    )}
                  </div>
                  <span className="t-meta shrink-0 tabular-nums" style={{ color: "var(--text-muted)" }}>
                    {source.relevance_pct}%
                  </span>
                </div>
              </a>
            ))
          )}
        </div>
      )}

      {/* ── Claims ───────────────────────────────────────────────────── */}
      {panel === "claims" && (
        <div className="max-h-[560px] overflow-y-auto">
          {claims.length === 0 ? (
            <EmptyState
              icon={<FileText size={20} />}
              title="No claims recorded"
              body="Claims appear once the analyst has cross-referenced the findings."
            />
          ) : (
            claims.map((claim) => {
              const tone =
                claim.confidence >= 0.7
                  ? "var(--success)"
                  : claim.confidence >= 0.4
                    ? "var(--warning)"
                    : "var(--danger)";
              return (
                <div
                  key={claim.id}
                  className="py-4"
                  style={{ borderBottom: "1px solid var(--border-subtle)" }}
                >
                  <div className="flex items-baseline gap-3">
                    <span
                      className="t-meta shrink-0 tabular-nums"
                      style={{ color: tone, width: 36 }}
                    >
                      {Math.round(claim.confidence * 100)}%
                    </span>
                    <p
                      className="min-w-0 flex-1 text-[12.5px] leading-relaxed"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {claim.text}
                    </p>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 pl-9">
                    <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                      {claim.agent}
                    </span>
                    {claim.source_urls.slice(0, 3).map((url) => (
                      <a
                        key={url}
                        href={url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="t-meta max-w-[200px] truncate transition-opacity hover:opacity-70"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {url}
                      </a>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
