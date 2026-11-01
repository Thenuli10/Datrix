"use client";
import { AlertOctagon, AlertTriangle, ArrowRightLeft, Info, Lightbulb } from "lucide-react";
import type { Dataset, Gap, GapSeverity, JoinSpec, ValidationReport } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPct, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

const GROUPS: { sev: GapSeverity; title: string; icon: typeof Info; tone: string }[] = [
  { sev: "blocker", title: "Blockers", icon: AlertOctagon, tone: "text-destructive" },
  { sev: "warning", title: "Warnings", icon: AlertTriangle, tone: "text-warning" },
  { sev: "info", title: "Info", icon: Info, tone: "text-info" },
];

export const VALIDATION_LABEL = {
  ready: { label: "Ready", variant: "success" as const },
  ready_with_warnings: { label: "Ready with warnings", variant: "warning" as const },
  needs_more_data: { label: "Needs more data", variant: "destructive" as const },
};

function GapItem({ gap }: { gap: Gap }) {
  return (
    <li className="border-t py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline">{humanize(gap.kind)}</Badge>
        {gap.column && <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{gap.column}</code>}
      </div>
      <p className="mt-1.5 text-sm">{gap.message}</p>
      {gap.suggestion && (
        <p className="mt-1 flex gap-1.5 text-sm text-muted-foreground">
          <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
          <span>{gap.suggestion}</span>
        </p>
      )}
    </li>
  );
}

export function GapReport({ report }: { report: ValidationReport }) {
  const s = VALIDATION_LABEL[report.status] ?? VALIDATION_LABEL.needs_more_data;
  return (
    <Card>
      <CardHeader className="sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>Gap report</CardTitle>
          {report.summary && <CardDescription>{report.summary}</CardDescription>}
        </div>
        <Badge variant={s.variant} className="self-start">
          {s.label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {report.gaps.length === 0 && <p className="text-sm text-muted-foreground">No gaps found. Your data covers the spec.</p>}
        {GROUPS.map(({ sev, title, icon: Icon, tone }) => {
          const items = report.gaps.filter((g) => g.severity === sev);
          if (!items.length) return null;
          return (
            <section key={sev} aria-label={title}>
              <h4 className={cn("flex items-center gap-1.5 text-sm font-medium", tone)}>
                <Icon className="size-4" aria-hidden /> {title} ({items.length})
              </h4>
              <ul className="mt-1">{items.map((g, i) => <GapItem key={i} gap={g} />)}</ul>
            </section>
          );
        })}
      </CardContent>
    </Card>
  );
}

export function JoinsList({ joins, datasets }: { joins: JoinSpec[]; datasets: Dataset[] }) {
  if (!joins.length) return null;
  const name = (id: number) => datasets.find((d) => d.id === id)?.original_name ?? `Dataset #${id}`;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Joins between files</CardTitle>
        <CardDescription>How your files will be combined before the analysis.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {joins.map((j, i) => {
            const rate = j.match_rate;
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm">
                <span className="min-w-0 truncate font-medium" title={name(j.left_dataset_id)}>
                  {name(j.left_dataset_id)}
                </span>
                <code className="rounded bg-muted px-1 text-xs">{j.left_key}</code>
                <ArrowRightLeft className="size-4 text-muted-foreground" aria-label={`${j.how} join`} />
                <span className="min-w-0 truncate font-medium" title={name(j.right_dataset_id)}>
                  {name(j.right_dataset_id)}
                </span>
                <code className="rounded bg-muted px-1 text-xs">{j.right_key}</code>
                <Badge variant="secondary">{j.how} join</Badge>
                {rate !== null && (
                  <Badge variant={rate >= 0.9 ? "success" : rate >= 0.6 ? "warning" : "destructive"}>{formatPct(rate, 0)} matched</Badge>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
