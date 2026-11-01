"use client";
import * as React from "react";
import { Check, Loader2, X } from "lucide-react";
import type { Run, StoredContractCheck } from "@/lib/types";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Stage names emitted by the orchestrator (Run.stage), matched by prefix. */
const FIRST_RUN_STAGES = [
  { label: "Queued", match: ["Queued"] },
  { label: "Preparing data", match: ["Preparing input data"] },
  { label: "Generating & running code", match: ["Generating analysis code", "Fixing results", "Running", "Executing"] },
  { label: "Checking results", match: ["Checking results"] },
  { label: "Composing dashboard", match: ["Composing dashboard", "Checking dashboard layout"] },
  { label: "Writing insights", match: ["Writing insights"] },
  { label: "Done", match: ["Completed"] },
];

const RERUN_STAGES = [
  { label: "Queued", match: ["Queued"] },
  { label: "Checking data contract", match: ["Checking data contract", "Checking drift"] },
  { label: "Running saved pipeline", match: ["Running saved pipeline", "Retraining", "Predicting"] },
  { label: "Quick sanity check", match: ["Quick sanity check"] },
  { label: "Refreshing dashboard", match: ["Refreshing dashboard", "Checking dashboard layout"] },
  { label: "Done", match: ["Completed"] },
];

export function stagesFor(run: Run) {
  return run.pipeline_id ? RERUN_STAGES : FIRST_RUN_STAGES;
}

export function StageIndicator({ run }: { run: Run }) {
  const stages = stagesFor(run);
  const stageText = run.stage ?? "";
  let current = stages.findIndex((s) => s.match.some((m) => stageText.startsWith(m)));
  if (run.status === "COMPLETED") current = stages.length - 1;
  const lastKnown = React.useRef(0);
  if (current >= 0) lastKnown.current = current;
  const idx = current >= 0 ? current : lastKnown.current;
  const failed = run.status === "FAILED";

  return (
    <ol className="space-y-0" aria-label="Run progress">
      {stages.map((s, i) => {
        const done = i < idx || run.status === "COMPLETED";
        const active = i === idx && !done;
        const isFail = failed && i === idx;
        return (
          <li key={s.label} className="relative flex gap-3 pb-4 last:pb-0">
            {i < stages.length - 1 && (
              <span aria-hidden className={cn("absolute top-6 left-[11px] h-[calc(100%-1.25rem)] w-px", done ? "bg-success" : "bg-border")} />
            )}
            <span
              className={cn(
                "relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium",
                done && "border-success bg-success text-white dark:text-background",
                active && !isFail && "border-primary text-primary",
                isFail && "border-destructive bg-destructive text-white dark:text-background",
                !done && !active && !isFail && "text-muted-foreground",
              )}
            >
              {isFail ? <X className="size-3.5" aria-hidden /> : done ? <Check className="size-3.5" aria-hidden /> : active ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : i + 1}
            </span>
            <div className="min-w-0 pt-0.5">
              <div className={cn("text-sm", (active || isFail) && "font-medium", !done && !active && !isFail && "text-muted-foreground")}>
                {s.label}
                <span className="sr-only">{done ? " (done)" : active ? " (in progress)" : isFail ? " (failed)" : ""}</span>
              </div>
              {(active || isFail) && stageText && stageText !== s.label && (
                <div className="truncate text-xs text-muted-foreground" title={stageText}>
                  {stageText}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function ContractCheckView({ check, compact }: { check: StoredContractCheck | null | undefined; compact?: boolean }) {
  if (!check || check.ok === undefined) return null;
  const errors = (check.issues ?? []).filter((i) => i.severity === "error");
  const warnings = (check.issues ?? []).filter((i) => i.severity === "warning");
  if (check.ok && !warnings.length) {
    return compact ? null : (
      <Alert variant="success" title="Data contract check passed">
        The new data matches the saved pipeline&apos;s columns, types and ranges.
      </Alert>
    );
  }
  return (
    <Alert variant={check.ok ? "warning" : "destructive"} title={check.ok ? "Data contract: warnings" : "Data contract check failed"}>
      <ul className="mt-1 space-y-1.5">
        {[...errors, ...warnings].map((i, n) => (
          <li key={n} className="flex flex-wrap items-start gap-1.5">
            <Badge variant={i.severity === "error" ? "destructive" : "warning"}>{i.severity}</Badge>
            {i.column && <code className="rounded bg-muted px-1 text-xs">{i.column}</code>}
            <span className="min-w-0 flex-1 basis-48">{i.message}</span>
          </li>
        ))}
      </ul>
    </Alert>
  );
}
