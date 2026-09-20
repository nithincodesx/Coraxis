"use client";

/**
 * Live execution stream.
 *
 * A structured timeline — timestamp, agent, action — rather than an
 * undifferentiated log dump. The events are also the resume cursor, so the
 * feed stays consistent across a dropped connection: a reconnecting client
 * replays exactly what it missed and appends.
 */

import { useEffect, useMemo, useRef } from "react";

import { extractAgentMessages, formatClock } from "../lib/derive";
import type { RunEvent } from "../lib/types";

interface Props {
  events: RunEvent[];
  streamStatus: "idle" | "connecting" | "open" | "closed" | "error";
  onClear: () => void;
}

/** Level → colour. Only error and success carry hue; the rest stay neutral. */
const LEVEL_COLOUR: Record<string, string> = {
  error: "var(--danger)",
  success: "var(--success)",
  warning: "var(--warning)",
};

const STREAM_LABEL: Record<Props["streamStatus"], string> = {
  idle: "Idle",
  connecting: "Reconnecting",
  open: "Live",
  closed: "Closed",
  error: "Disconnected",
};

export default function EventFeed({ events, streamStatus, onClear }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Only auto-scroll when the user is already at the bottom, so reading back
  // through history is not yanked away by each new event.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    if (distanceFromBottom < 80) node.scrollTop = node.scrollHeight;
  }, [events.length]);

  const messages = useMemo(() => extractAgentMessages(events), [events]);

  const live = streamStatus === "open";
  const failed = streamStatus === "error";

  return (
    <div
      className="overflow-hidden rounded-2xl"
      style={{ background: "var(--surface-sunken)", border: "1px solid var(--border-subtle)" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: "1px solid var(--border-subtle)" }}
      >
        <div className="flex items-center gap-2.5">
          <span className={`dot ${live ? "dot-live" : failed ? "dot-error" : ""}`} aria-hidden />
          <span className="t-label" style={{ color: "var(--text-secondary)" }}>
            Execution Feed
          </span>
          <span className="t-meta" style={{ color: "var(--text-faint)" }}>
            {events.length}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="t-meta" style={{ color: live ? "var(--success)" : "var(--text-faint)" }}>
            {STREAM_LABEL[streamStatus]}
          </span>
          {events.length > 0 && (
            <button
              type="button"
              onClick={onClear}
              className="t-meta transition-colors hover:opacity-70"
              style={{ color: "var(--text-muted)" }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Agent-to-agent bus */}
      {messages.length > 0 && (
        <div
          className="px-4 py-3"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <p className="t-label mb-2" style={{ color: "var(--text-faint)" }}>
            Agent bus · {messages.length}
          </p>
          <div className="max-h-24 space-y-1 overflow-y-auto pr-1">
            {messages.slice(-30).map((message, index) => (
              <p key={index} className="t-meta" style={{ lineHeight: 1.6 }}>
                <span style={{ color: "var(--text-faint)" }}>{formatClock(message.at)}</span>
                <span style={{ color: "var(--text-secondary)" }}>
                  {" "}
                  {message.from} → {message.to}{" "}
                </span>
                <span style={{ color: "var(--text-muted)" }}>{message.message}</span>
              </p>
            ))}
          </div>
        </div>
      )}

      {/* Timeline */}
      <div ref={scrollRef} className="max-h-80 min-h-[180px] overflow-y-auto">
        {events.length === 0 ? (
          <div className="flex h-[180px] flex-col items-center justify-center gap-1.5">
            <p className="t-meta" style={{ color: "var(--text-muted)" }}>
              No activity yet
            </p>
            <p className="t-meta" style={{ color: "var(--text-faint)" }}>
              Run a query to begin the stream
            </p>
          </div>
        ) : (
          events.map((event) => {
            const colour = LEVEL_COLOUR[event.level];
            return (
              <div
                key={event.id}
                className="flex items-start gap-3 px-4 py-2 transition-colors"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <span
                  className="t-meta shrink-0 tabular-nums"
                  style={{ color: "var(--text-faint)", width: 62 }}
                >
                  {formatClock(event.created_at)}
                </span>
                <span
                  className="t-meta shrink-0 uppercase"
                  style={{ color: "var(--text-secondary)", width: 96 }}
                  title={event.agent}
                >
                  {event.agent || "system"}
                </span>
                <span
                  className="min-w-0 flex-1 text-[11.5px] leading-relaxed"
                  style={{ color: colour ?? "var(--text-muted)", fontFamily: "var(--font-mono)" }}
                >
                  {event.message || event.type}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
