"use client";
import * as React from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, LayoutTemplate, ShieldAlert } from "lucide-react";
import type { DashboardQAReport, SanityIssue, SanityReport, Severity } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

const SEV_VARIANT: Record<Severity, "destructive" | "warning" | "secondary"> = {
  high: "destructive",
  medium: "warning",
  low: "secondary",
};

const LAYER_LABEL: Record<number, string> = {
  1: "Rule check",
  2: "Recalculation",
  3: "AI review",
  4: "vs. past runs",
};

function IssueRow({ issue }: { issue: SanityIssue }) {
  return (
    <li className="flex flex-col gap-1 border-t py-2.5 first:border-t-0 sm:flex-row sm:items-start sm:gap-3">
      <div className="flex shrink-0 items-center gap-1.5">
        <Badge variant={SEV_VARIANT[issue.severity]}>{issue.severity}</Badge>
        <Badge variant="outline">{humanize(issue.check)}</Badge>
      </div>
      <div className="min-w-0 flex-1 text-sm">
        <p>{issue.message}</p>
        {issue.suggested_fix && <p className="mt-0.5 text-muted-foreground">Suggested fix: {issue.suggested_fix}</p>}
      </div>
      <span className="shrink-0 text-xs text-muted-foreground">{LAYER_LABEL[issue.layer] ?? `Layer ${issue.layer}`}</span>
    </li>
  );
}

/**
 * Results sanity status (§7a): "Checks: N passed, M warnings" with an expandable issue list,
 * a red banner when status is `fail`, and dashboard QA issues (§7b) collapsed underneath.
 */
export function ChecksBanner({ sanity, qa }: { sanity: SanityReport | null; qa?: DashboardQAReport | null }) {
  const [open, setOpen] = React.useState(false);
  const [qaOpen, setQaOpen] = React.useState(false);
  const listId = React.useId();
  const qaId = React.useId();
  if (!sanity && !qa) return null;

  const issues = sanity?.issues ?? [];
  const warnings = issues.length;
  const passed = sanity?.checks_passed ?? 0;
  const status = sanity?.status ?? "pass";
  const fail = status === "fail";
  const qaIssues = (qa?.issues ?? []).filter((i) => !i.auto_fixed);
  const qaFixed = (qa?.issues ?? []).filter((i) => i.auto_fixed).length;

  return (
    <div className="space-y-2">
      {sanity && (
        <div
          role={fail ? "alert" : "status"}
          className={cn(
            "rounded-xl border",
            fail && "border-destructive/50 bg-destructive/8",
            status === "warn" && "border-warning/40 bg-warning/6",
            status === "pass" && "bg-card",
          )}
        >
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            disabled={!warnings}
            aria-expanded={warnings ? open : undefined}
            aria-controls={warnings ? listId : undefined}
            className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left disabled:cursor-default"
          >
            {fail ? (
              <ShieldAlert className="size-5 shrink-0 text-destructive" aria-hidden />
            ) : status === "warn" ? (
              <AlertTriangle className="size-5 shrink-0 text-warning" aria-hidden />
            ) : (
              <CheckCircle2 className="size-5 shrink-0 text-success" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">
                {fail
                  ? "These results did not pass all sanity checks: review the issues before relying on them."
                  : `Checks: ${passed} passed${warnings ? `, ${warnings} warning${warnings === 1 ? "" : "s"}` : ""}`}
              </div>
              {fail && (
                <div className="text-xs text-muted-foreground">
                  Checks: {passed} passed, {warnings} issue{warnings === 1 ? "" : "s"}
                </div>
              )}
            </div>
            {warnings > 0 && (
              <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
            )}
          </button>
          {open && warnings > 0 && (
            <ul id={listId} className="border-t px-4 py-1">
              {issues.map((i, n) => (
                <IssueRow key={n} issue={i} />
              ))}
            </ul>
          )}
        </div>
      )}

      {qa && (qaIssues.length > 0 || qaFixed > 0) && (
        <div className="rounded-xl border bg-card">
          <button
            type="button"
            onClick={() => setQaOpen((o) => !o)}
            aria-expanded={qaOpen}
            aria-controls={qaId}
            className="flex w-full items-center gap-3 rounded-xl px-4 py-2.5 text-left"
          >
            <LayoutTemplate className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="flex-1 text-xs text-muted-foreground">
              Dashboard layout check: {qaFixed} auto-fixed
              {qaIssues.length ? `, ${qaIssues.length} open note${qaIssues.length === 1 ? "" : "s"}` : ""}
              {qa.rounds ? ` · ${qa.rounds} round${qa.rounds === 1 ? "" : "s"}` : ""}
            </span>
            <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", qaOpen && "rotate-180")} aria-hidden />
          </button>
          {qaOpen && (
            <ul id={qaId} className="border-t px-4 py-1 text-sm">
              {(qa.issues ?? []).map((i, n) => (
                <li key={n} className="flex flex-wrap items-start gap-2 border-t py-2 first:border-t-0">
                  <Badge variant={i.auto_fixed ? "success" : SEV_VARIANT[i.severity]}>{i.auto_fixed ? "fixed" : i.severity}</Badge>
                  <Badge variant="outline">{humanize(i.rule)}</Badge>
                  {i.widget_id && <code className="rounded bg-muted px-1 text-xs">{i.widget_id}</code>}
                  <span className="min-w-0 flex-1 basis-60">{i.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
