"use client";
import * as React from "react";
import { useParams } from "next/navigation";
import { errorMessage } from "./api";

export interface LoadState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: React.Dispatch<React.SetStateAction<T | undefined>>;
}

/** Minimal data loader: runs `fn` on mount and whenever `deps` change. */
export function useLoad<T>(fn: () => Promise<T>, deps: React.DependencyList): LoadState<T> {
  const [data, setData] = React.useState<T | undefined>(undefined);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const fnRef = React.useRef(fn);
  fnRef.current = fn;
  const seq = React.useRef(0);

  const reload = React.useCallback(async () => {
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await fnRef.current();
      if (my === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (my === seq.current) setError(errorMessage(e));
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

/**
 * Guard for actions that cost LLM credits: while one call is in flight, further triggers
 * (double-clicks, Enter + click, re-renders, StrictMode effects) are ignored. Unlike a
 * `busy` state, the ref flips synchronously, so two clicks in the same frame can't both fire.
 */
export function useSingleFlight() {
  const inFlight = React.useRef(false);
  return React.useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    if (inFlight.current) return undefined;
    inFlight.current = true;
    try {
      return await fn();
    } finally {
      inFlight.current = false;
    }
  }, []);
}

/** Run `fn` every `ms` while `active`. */
export function useInterval(fn: () => void, ms: number, active = true) {
  const ref = React.useRef(fn);
  ref.current = fn;
  React.useEffect(() => {
    if (!active) return;
    const t = setInterval(() => ref.current(), ms);
    return () => clearInterval(t);
  }, [ms, active]);
}

/** Numeric `[id]` route param. */
export function useIdParam(name = "id"): number {
  const params = useParams<Record<string, string>>();
  return Number(params?.[name]);
}
