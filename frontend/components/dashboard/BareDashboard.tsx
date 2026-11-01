"use client";
import * as React from "react";
import type { DashboardSpec, Results } from "@/lib/types";
import { applyTheme } from "@/components/layout/theme";
import { SpecRenderer } from "./SpecRenderer";
import { ResultsSummaryLine } from "./DashboardView";

const READY_TIMEOUT_MS = 20000;

/**
 * Sets `data-ready="true"` on <body> and on the root element once every widget has drawn
 * (or on timeout / error), so the Playwright screenshot service knows when to capture.
 */
export function useReadyFlag(rootRef: React.RefObject<HTMLElement | null>) {
  const [ready, setReady] = React.useState(false);
  const markReady = React.useCallback((reason: "rendered" | "timeout" | "error" | "empty" = "rendered") => {
    setReady(true);
    document.body.dataset.ready = "true";
    document.body.dataset.readyReason = reason;
    if (rootRef.current) rootRef.current.dataset.ready = "true";
  }, [rootRef]);
  React.useEffect(() => {
    delete document.body.dataset.ready;
    const t = setTimeout(() => markReady("timeout"), READY_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [markReady]);
  return { ready, markReady };
}

/** Honors `?theme=light|dark` (falls back to the saved / system theme). */
export function useThemeParam(theme: string | null) {
  React.useEffect(() => {
    if (theme === "light" || theme === "dark") applyTheme(theme);
  }, [theme]);
}

export function BareDashboard({
  spec,
  results,
  onReady,
}: {
  spec: DashboardSpec;
  results: Results;
  onReady: () => void;
}) {
  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">{spec.title || results.summary.title}</h1>
        <ResultsSummaryLine results={results} />
      </header>
      <SpecRenderer spec={spec} results={results} allTabs onReady={onReady} />
    </div>
  );
}
