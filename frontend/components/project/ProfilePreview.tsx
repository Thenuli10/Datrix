"use client";
import * as React from "react";
import { Trash2 } from "lucide-react";
import type { Dataset } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDateTime, formatValue } from "@/lib/format";
import { cn } from "@/lib/utils";

function cell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return formatValue(v, "number");
  return String(v);
}

/** Uploaded files with their profile (columns, types, nulls, stats) and sample rows. */
export function ProfilePreview({
  datasets,
  onDelete,
  deleting,
}: {
  datasets: Dataset[];
  onDelete?: (d: Dataset) => void;
  deleting?: number | null;
}) {
  const [selected, setSelected] = React.useState<number>(datasets[0]?.id ?? 0);
  React.useEffect(() => {
    if (!datasets.some((d) => d.id === selected)) setSelected(datasets[0]?.id ?? 0);
  }, [datasets, selected]);
  const ds = datasets.find((d) => d.id === selected);
  if (!datasets.length) return null;
  const p = ds?.profile_json;

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>Uploaded files</CardTitle>
          <CardDescription>
            {datasets.length} file{datasets.length === 1 ? "" : "s"}. Only the profile and a small sample are sent to the AI, never the full data.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="profile-file" className="sr-only">
            File to preview
          </label>
          <Select id="profile-file" wrapperClassName="w-56 max-w-full" value={selected} onChange={(e) => setSelected(Number(e.target.value))}>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.original_name}
              </option>
            ))}
          </Select>
          {onDelete && ds && (
            <Button
              variant="outline"
              size="icon"
              aria-label={`Remove ${ds.original_name}`}
              title="Remove file"
              loading={deleting === ds.id}
              onClick={() => onDelete(ds)}
            >
              {deleting !== ds.id && <Trash2 />}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {!ds ? null : !p ? (
          <p className="text-sm text-muted-foreground">This file has not been profiled yet.</p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs">
              <Badge variant="secondary">{p.row_count.toLocaleString()} rows</Badge>
              <Badge variant="secondary">{p.column_count} columns</Badge>
              <Badge variant="secondary">{ds.file_type.toUpperCase()}</Badge>
              <Badge variant="outline">uploaded {formatDateTime(ds.uploaded_at)}</Badge>
            </div>
            <Tabs defaultValue="columns">
              <TabsList>
                <TabsTrigger value="columns">Columns</TabsTrigger>
                <TabsTrigger value="sample">Sample rows</TabsTrigger>
              </TabsList>
              <TabsContent value="columns" className="mt-3">
                <Table wrapperClassName="max-h-96 rounded-md border">
                  <THead className="sticky top-0 bg-muted">
                    <TR className="hover:bg-transparent">
                      <TH>Column</TH>
                      <TH>Type</TH>
                      <TH className="text-right">Nulls</TH>
                      <TH className="text-right">Unique</TH>
                      <TH>Range / top values</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {p.columns.map((c) => (
                      <TR key={c.name}>
                        <TD className="max-w-48 truncate font-medium" title={c.name}>
                          {c.name}
                        </TD>
                        <TD>
                          <Badge variant="secondary">{c.inferred_type}</Badge>
                        </TD>
                        <TD className={cn("text-right tabular-nums", c.null_pct > 20 && "text-warning")}>
                          {`${c.null_pct.toFixed(c.null_pct > 0 && c.null_pct < 1 ? 2 : 1)}%`}
                        </TD>
                        <TD className="text-right tabular-nums">{c.unique_count.toLocaleString()}</TD>
                        <TD className="max-w-72 truncate text-muted-foreground" title={c.top_values.map(([v, n]) => `${v} (${n})`).join(", ")}>
                          {c.min !== null && c.min !== undefined && c.max !== null && c.max !== undefined
                            ? `${cell(c.min)} – ${cell(c.max)}${c.mean !== null ? ` · mean ${formatValue(c.mean)}` : ""}`
                            : c.top_values.slice(0, 3).map(([v, n]) => `${v} (${n})`).join(", ") || c.sample_values.slice(0, 3).join(", ")}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TabsContent>
              <TabsContent value="sample" className="mt-3">
                {p.sample_rows.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No sample rows.</p>
                ) : (
                  <Table wrapperClassName="max-h-96 rounded-md border" className="text-xs">
                    <THead className="sticky top-0 bg-muted">
                      <TR className="hover:bg-transparent">
                        {Object.keys(p.sample_rows[0]).map((k) => (
                          <TH key={k}>{k}</TH>
                        ))}
                      </TR>
                    </THead>
                    <TBody>
                      {p.sample_rows.map((r, i) => (
                        <TR key={i}>
                          {Object.keys(p.sample_rows[0]).map((k) => (
                            <TD key={k} className="max-w-48 truncate whitespace-nowrap" title={String(r[k] ?? "")}>
                              {cell(r[k])}
                            </TD>
                          ))}
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </TabsContent>
            </Tabs>
          </>
        )}
      </CardContent>
    </Card>
  );
}
