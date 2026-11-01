"use client";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/common";
import { DashboardView, ResultsSummaryLine } from "@/components/dashboard/DashboardView";
import { BareDashboard, useReadyFlag } from "@/components/dashboard/BareDashboard";
import { sampleInsights, sampleQA, sampleResults, sampleSanity, sampleSpec } from "@/lib/fixtures/sample-results";
import type { SanityReport } from "@/lib/types";

export function Preview() {
  const [mode, setMode] = React.useState<"app" | "bare">("app");
  const [fail, setFail] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const { ready, markReady } = useReadyFlag(rootRef);
  const onReady = React.useCallback(() => markReady("rendered"), [markReady]);

  const sanity: SanityReport = fail
    ? {
        ...sampleSanity,
        status: "fail",
        issues: [
          ...sampleSanity.issues,
          {
            severity: "high",
            check: "target_leakage",
            message: "AUC 0.995: 'cancel_date' is derived from the target.",
            suggested_fix: "Drop cancel_date from the features.",
            layer: 3,
          },
        ],
      }
    : sampleSanity;

  return (
    <div ref={rootRef}>
      <PageHeader
        eyebrow="Dev preview · fixture data"
        title={sampleSpec.title}
        description={<ResultsSummaryLine results={sampleResults} />}
        actions={
          <>
            <Badge variant={ready ? "success" : "secondary"}>data-ready: {String(ready)}</Badge>
            <Button variant="outline" size="sm" onClick={() => setFail((f) => !f)}>
              {fail ? "Show warn status" : "Show fail status"}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setMode((m) => (m === "app" ? "bare" : "app"))}>
              {mode === "app" ? "All tabs (render mode)" : "App mode (tabs)"}
            </Button>
          </>
        }
      />
      {mode === "app" ? (
        <DashboardView
          payload={{ spec: sampleSpec, results: sampleResults, sanity, dashboard_qa: sampleQA, insights_md: sampleInsights, drift: null }}
          onReady={onReady}
        />
      ) : (
        <BareDashboard spec={sampleSpec} results={sampleResults} onReady={onReady} />
      )}
    </div>
  );
}
