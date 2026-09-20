"use client";

/**
 * Minimal data-fetching hook.
 *
 * The app has a handful of read-only resources (agents, teams, credentials,
 * providers, runs, metrics) that all want the same three things: a loading
 * flag, a surfaced error, and a way to refetch. This covers that without
 * pulling in a query library.
 *
 * The `fetcher` is held in a ref rather than a dependency. Callers routinely
 * pass an inline arrow function, and depending on its identity would refetch on
 * every render. To refetch when something else changes — the selected run id,
 * say — pass a `refreshKey`; it is a single string rather than a dependency
 * array so the effect's dependency list stays statically verifiable.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/api";

export interface AsyncDataResult<T> {
  data: T | null;
  error: string | null;
  isLoading: boolean;
  /** True only for the first load, so a refetch does not blank the screen. */
  isInitialLoading: boolean;
  refetch: () => Promise<void>;
  setData: (value: T | null) => void;
}

export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  { enabled = true, refreshKey = "" }: { enabled?: boolean; refreshKey?: string } = {},
): AsyncDataResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  // Kept in a ref so an inline arrow fetcher does not retrigger the effect on
  // every render. Assigned in an effect rather than during render, because
  // writing to a ref while rendering is not safe under concurrent rendering.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await fetcherRef.current();
      if (!mountedRef.current) return;
      setData(result);
      setError(null);
    } catch (caught) {
      if (!mountedRef.current) return;
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : "Something went wrong.",
      );
    } finally {
      if (mountedRef.current) {
        setIsLoading(false);
        setHasLoaded(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    // `load` sets the loading flag before its first await, which this rule
    // reads as a synchronous setState inside an effect. It is the documented
    // data-fetching pattern and the flag is load-bearing: without it a refetch
    // renders stale data with no indication that a request is in flight. The
    // alternative — deriving loading from a request counter — reintroduces the
    // same render one tick later.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [enabled, load, refreshKey]);

  return {
    data,
    error,
    // Derived rather than stored: a disabled hook is never "loading", and
    // setting that flag from an effect would cause a cascading render.
    isLoading: enabled && isLoading,
    isInitialLoading: enabled && isLoading && !hasLoaded,
    refetch: load,
    setData,
  };
}
