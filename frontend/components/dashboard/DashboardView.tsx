"use client";
import * as React from "react";
import { AlertTriangle } from "lucide-react";
import type { DashboardPayload, DashboardSpec, DriftReport, Results } from "@/lib/types";
import { Alert } from "@/components/ui/alert";
import { EmptyState } from "@/components/layout/common";
import { formatDate, formatValue } from "@/lib/format";
import { ChecksBanner } from "./ChecksBanner";
import { InsightsPanel } from "./InsightsPanel";
import { SpecRenderer } from "./SpecRenderer";

export function DriftAlert({ drift }: { drift: DriftReport | null | undefined }) {
  if (!drift?.drifted) return null;
  const cols = drift.columns.filter((c) => c.drifted);
  return (
    <Alert variant="warning" title="Data drift detected">
      <p>
        The new data looks different from the training data in {cols.length} column{cols.length === 1 ? "" : "s"}. Predictions
        may be less reliable; consider retraining.
      </p>
      {cols.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-1.5">
          {cols.map((c) => (
            <li key={c.column} className="rounded bg-warning/12 px-1.5 py-0.5 text-xs">
              {c.column} ({c.method.toUpperCase()} {c.statistic.toFixed(3)}
              {c.p_value !== null ? `, p=${c.p_value.toPrecision(2)}` : ""})
            </li>
          ))}
        </ul>
      )}
    </Alert>
  );
}

export function ResultsSummaryLine({ results }: { results: Results }) {
  const s = results.summary;
  const parts = [`${formatValue(s.rows_processed, "integer")} rows processed`];
  if (s.rows_dropped) parts.push(`${formatValue(s.rows_dropped, "integer")} dropped${s.drop_reasons?.length ? ` (${s.drop_reasons.join("; ")})` : ""}`);
  if (s.input_date_min && s.input_date_max) parts.push(`${formatDate(s.input_date_min)} – ${formatDate(s.input_date_max)}`);
  return <p className="text-sm text-muted-foreground">{parts.join(" · ")}</p>;
}

/** Full dashboard (checks, drift, insights, widgets) for the in-app dashboard page. */
export function DashboardView({
  payload,
  onReady,
}: {
  payload: Pick<DashboardPayload, "spec" | "results" | "sanity" | "dashboard_qa" | "insights_md" | "drift">;
  onReady?: () => void;
}) {
  const { spec, results } = payload;
  if (!results) {
    return <EmptyState icon={AlertTriangle} title="No results for this run" description="The run did not produce results.json." />;
  }
  return (
    <div className="space-y-5">
      <ChecksBanner sanity={payload.sanity} qa={payload.dashboard_qa} />
      <DriftAlert drift={payload.drift} />
      <InsightsPanel markdown={payload.insights_md} fallback={results.insights_raw} />
      {spec ? (
        <SpecRenderer spec={spec as DashboardSpec} results={results} onReady={onReady} />
      ) : (
        <EmptyState title="No dashboard spec" description="The dashboard has not been composed for this run yet." />
      )}
    </div>
  );
}
