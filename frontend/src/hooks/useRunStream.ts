"use client";

/**
 * Live progress for one research run.
 *
 * Replaces two things the old frontend did badly. It polled `/api/status` every
 * 1.2 seconds to reconstruct agent progress, and it held a second, unrelated
 * `EventSource` open on `/api/comms/stream` that only ever carried agent
 * chatter. Both are now one stream, and the server is the source of truth.
 *
 * `EventSource` is not used, for two reasons: it cannot send an
 * `Authorization` header, and it cannot resume with an explicit cursor. A
 * `fetch`-based reader can do both, which is what makes gap-free reconnect
 * possible — every event is persisted with a monotonic `seq` before it is
 * broadcast, so reconnecting with `Last-Event-ID: <last seq seen>` returns
 * exactly what was missed.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, authHeaders, runsApi } from "../lib/api";
import { clearSession, refreshAccessToken } from "../lib/session";
import type { RunEvent } from "../lib/types";

/** Backoff schedule for reconnect attempts, in milliseconds. */
const RECONNECT_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000];

export type StreamStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface UseRunStreamResult {
  events: RunEvent[];
  status: StreamStatus;
  error: string | null;
  /** Highest `seq` received. The cursor a reconnect would resume from. */
  lastSeq: number;
  /** Discard the buffer and reconnect from the beginning. */
  restart: () => void;
}

interface Options {
  /** Start the stream only when true. */
  enabled?: boolean;
  /** Cap the retained buffer so a very long run cannot exhaust memory. */
  maxEvents?: number;
}

/**
 * Parse one SSE frame.
 *
 * The wire format is line-oriented: `field: value` pairs terminated by a blank
 * line. A leading `:` marks a comment (the server's keepalives), which exists
 * purely to hold the connection open and must not be surfaced.
 */
function parseFrame(frame: string): { id?: string; event?: string; data?: string } | null {
  const parsed: { id?: string; event?: string; data?: string } = {};
  let sawField = false;

  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    const field = line.slice(0, colon).trim();
    const value = line.slice(colon + 1).replace(/^ /, "");
    sawField = true;
    if (field === "id") parsed.id = value;
    else if (field === "event") parsed.event = value;
    else if (field === "data") {
      parsed.data = parsed.data ? `${parsed.data}\n${value}` : value;
    }
  }

  return sawField ? parsed : null;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

export function useRunStream(
  runId: string | null,
  { enabled = true, maxEvents = 2_000 }: Options = {},
): UseRunStreamResult {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSeq, setLastSeq] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const cursorRef = useRef(0);
  const attemptRef = useRef(0);
  const closedRef = useRef(false);

  /**
   * Open the stream and keep it open.
   *
   * Written as one loop rather than a function that reschedules itself: a
   * self-referencing callback cannot be expressed in a `useCallback`
   * dependency list without lying about what it depends on.
   */
  const connect = useCallback(async () => {
    if (!runId) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    attemptRef.current = 0;

    while (!controller.signal.aborted && !closedRef.current) {
      let retryable = true;

      try {
        const response = await fetch(runsApi.streamPath(runId), {
          headers: authHeaders(
            // Resume exactly where the last connection stopped.
            cursorRef.current > 0 ? { "Last-Event-ID": String(cursorRef.current) } : {},
          ),
          signal: controller.signal,
          cache: "no-store",
        });

        if (response.status === 401) {
          // The stream cannot retry through the client, so refresh here and let
          // the loop reconnect with the new token.
          const refreshed = await refreshAccessToken("/api/v1");
          if (!refreshed) {
            clearSession();
            setStatus("error");
            setError("Your session expired. Sign in again.");
            return;
          }
          retryable = false;
          throw new ApiError("Retrying with a fresh token.", 401, "unauthenticated", null);
        }

        if (!response.ok || !response.body) {
          throw new ApiError(
            `The progress stream refused the connection (${response.status}).`,
            response.status,
            `http_${response.status}`,
            null,
          );
        }

        setStatus("open");
        setError(null);
        attemptRef.current = 0;

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Frames are separated by a blank line. Anything after the last
          // separator is a partial frame and must survive to the next read.
          let separator = buffer.indexOf("\n\n");
          while (separator !== -1) {
            const frame = buffer.slice(0, separator);
            buffer = buffer.slice(separator + 2);

            const parsed = parseFrame(frame);
            if (parsed?.data) {
              if (parsed.event === "stream.closed") {
                closedRef.current = true;
                setStatus("closed");
                return;
              }
              try {
                const event = JSON.parse(parsed.data) as RunEvent;
                if (typeof event.seq === "number" && event.seq > cursorRef.current) {
                  cursorRef.current = event.seq;
                  setLastSeq(event.seq);
                  setEvents((previous) => {
                    const next = [...previous, event];
                    return next.length > maxEvents ? next.slice(-maxEvents) : next;
                  });
                }
              } catch {
                // A malformed frame is not worth tearing the stream down for.
              }
            }

            separator = buffer.indexOf("\n\n");
          }
        }
      } catch (caught) {
        if (controller.signal.aborted) return;
        if (!(caught instanceof ApiError && caught.status === 401)) {
          setError(caught instanceof Error ? caught.message : "The progress stream failed.");
        }
      }

      if (controller.signal.aborted || closedRef.current) return;

      // A 401 that we just refreshed should retry immediately; anything else
      // backs off so a downed server is not hammered.
      if (retryable) {
        setStatus((current) => (current === "open" ? "connecting" : current));
        const delay =
          RECONNECT_DELAYS_MS[Math.min(attemptRef.current, RECONNECT_DELAYS_MS.length - 1)];
        attemptRef.current += 1;
        await sleep(delay, controller.signal);
      }
    }
  }, [runId, maxEvents]);

  const restart = useCallback(() => {
    cursorRef.current = 0;
    attemptRef.current = 0;
    closedRef.current = false;
    setEvents([]);
    setLastSeq(0);
    setError(null);
    void connect();
  }, [connect]);

  useEffect(() => {
    if (!runId || !enabled) return;

    closedRef.current = false;
    // `connect` reaches its first setState only after `await fetch(...)`, so
    // nothing is set synchronously here. The rule cannot see past the async
    // boundary and reports a false positive; connecting to an external stream
    // and reporting its status is what an effect is for.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void connect();

    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [runId, enabled, connect]);

  // Derived, not stored: a stream that was never started is idle regardless of
  // what the last run left in state, and setting that from an effect would
  // cause a cascading render on mount.
  const isActive = Boolean(runId) && enabled;

  return {
    events,
    status: isActive ? status : "idle",
    error: isActive ? error : null,
    lastSeq,
    restart,
  };
}
