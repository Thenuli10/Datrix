"use client";
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { api, errorMessage } from "@/lib/api";
import { useIdParam } from "@/lib/hooks";
import type { DashboardPayload } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";
import { BareDashboard, useReadyFlag, useThemeParam } from "@/components/dashboard/BareDashboard";

/**
 * Bare dashboard page (no nav/chrome) used by the backend's Playwright screenshot service
 * (PLAN §7b). Renders every tab stacked; sets data-ready="true" once charts have drawn.
 */
function RenderInner() {
  const id = useIdParam();
  const search = useSearchParams();
  useThemeParam(search.get("theme"));
  const rootRef = React.useRef<HTMLDivElement>(null);
  const { markReady } = useReadyFlag(rootRef);
  const [payload, setPayload] = React.useState<DashboardPayload | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api
      .getDashboard(id)
      .then((p) => {
        setPayload(p);
        if (!p.spec || !p.results) markReady("empty");
      })
      .catch((e) => {
        setError(errorMessage(e));
        markReady("error");
      });
  }, [id, markReady]);

  const onReady = React.useCallback(() => markReady("rendered"), [markReady]);

  return (
    <div ref={rootRef} id="dashboard-root" className="min-h-screen bg-background px-4 py-5 sm:px-6">
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : !payload ? (
        <div className="space-y-4">
          <Skeleton className="h-7 w-72 max-w-full" />
          <Skeleton className="h-64" />
        </div>
      ) : payload.spec && payload.results ? (
        <BareDashboard spec={payload.spec} results={payload.results} onReady={onReady} />
      ) : (
        <p className="text-sm text-muted-foreground">No dashboard for this run.</p>
      )}
    </div>
  );
}

export default function RenderRunPage() {
  return (
    <React.Suspense fallback={null}>
      <RenderInner />
    </React.Suspense>
  );
}
