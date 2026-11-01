"use client";
import { CheckCircle2, Circle, Download, Info } from "lucide-react";
import type { ColumnMapping, DataSpec } from "@/lib/types";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** The data spec as a checklist (§2.3), with a template CSV download. Mapped columns are ticked. */
export function DataSpecChecklist({
  projectId,
  spec,
  mapping,
  compact = false,
}: {
  projectId: number;
  spec: DataSpec;
  mapping?: ColumnMapping[];
  compact?: boolean;
}) {
  const mapped = new Set((mapping ?? []).filter((m) => m.source_column).map((m) => m.spec_column));
  const required = spec.columns.filter((c) => c.required);
  const optional = spec.columns.filter((c) => !c.required);
  const doneRequired = required.filter((c) => mapped.has(c.name)).length;

  const renderCol = (c: DataSpec["columns"][number]) => {
    const ok = mapped.has(c.name);
    return (
      <li key={c.name} className="flex gap-3 border-t py-2.5 first:border-t-0">
        {mapping ? (
          ok ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-label="Mapped" />
          ) : (
            <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-label="Not mapped yet" />
          )
        ) : (
          <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium">{c.name}</code>
            <Badge variant="secondary">{c.type}</Badge>
            {!c.required && <Badge variant="outline">optional</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{c.description}</p>
          {!compact && c.example_values?.length > 0 && (
            <p className="mt-0.5 truncate text-xs text-muted-foreground" title={c.example_values.join(", ")}>
              e.g. {c.example_values.slice(0, 4).join(", ")}
            </p>
          )}
        </div>
      </li>
    );
  };

  return (
    <Card>
      <CardHeader className="sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>Data you need</CardTitle>
          <CardDescription>
            One row = <span className="font-medium text-foreground">{spec.granularity}</span>. At least{" "}
            {spec.min_rows.toLocaleString()} rows
            {spec.min_date_range_days ? `, covering ≥ ${spec.min_date_range_days} days` : ""}.
            {mapping && ` ${doneRequired}/${required.length} required columns mapped.`}
          </CardDescription>
        </div>
        <a href={api.templateCsvUrl(projectId)} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "shrink-0")} download>
          <Download /> Template CSV
        </a>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul aria-label="Required columns">{required.map(renderCol)}</ul>
        {optional.length > 0 && (
          <div>
            <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Optional</h4>
            <ul aria-label="Optional columns">{optional.map(renderCol)}</ul>
          </div>
        )}
        {(spec.notes || spec.multiple_files_hint) && (
          <div className="space-y-1 rounded-lg bg-muted/60 p-3 text-sm">
            {spec.notes && (
              <p className="flex gap-2">
                <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
                <span>{spec.notes}</span>
              </p>
            )}
            {spec.multiple_files_hint && (
              <p className="flex gap-2">
                <Info className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
                <span>
                  <span className="font-medium">Multiple files:</span> {spec.multiple_files_hint}
                </span>
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
