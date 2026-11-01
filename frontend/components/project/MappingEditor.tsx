"use client";
import * as React from "react";
import { Save, Undo2 } from "lucide-react";
import type { ColumnMapping, DataSpec, Dataset } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

function initialRows(spec: DataSpec, mapping: ColumnMapping[]): ColumnMapping[] {
  const byCol = new Map(mapping.map((m) => [m.spec_column, m]));
  const rows = spec.columns.map(
    (c) => byCol.get(c.name) ?? { spec_column: c.name, dataset_id: 0, source_column: "", transform: "" },
  );
  // keep mappings for columns no longer in the spec, too
  for (const m of mapping) if (!spec.columns.some((c) => c.name === m.spec_column)) rows.push(m);
  return rows;
}

/** Editable spec column → dataset/column mapping, saved via PUT /projects/{id}/column-mapping. */
export function MappingEditor({
  spec,
  mapping,
  datasets,
  onSave,
  saving,
}: {
  spec: DataSpec;
  mapping: ColumnMapping[];
  datasets: Dataset[];
  onSave: (m: ColumnMapping[]) => void | Promise<void>;
  saving?: boolean;
}) {
  const [rows, setRows] = React.useState(() => initialRows(spec, mapping));
  React.useEffect(() => setRows(initialRows(spec, mapping)), [spec, mapping]);

  const columnsOf = React.useCallback(
    (dsId: number) => datasets.find((d) => d.id === dsId)?.profile_json?.columns ?? [],
    [datasets],
  );
  const specCol = (name: string) => spec.columns.find((c) => c.name === name);
  const dirty = JSON.stringify(rows) !== JSON.stringify(initialRows(spec, mapping));

  const update = (i: number, patch: Partial<ColumnMapping>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const missingRequired = rows.filter((r) => specCol(r.spec_column)?.required && !r.source_column).length;

  return (
    <Card>
      <CardHeader className="sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle>Column mapping</CardTitle>
          <CardDescription>
            Which of your columns fills each column of the spec. Fix anything the validator got wrong, then save.
            {missingRequired > 0 && ` ${missingRequired} required column${missingRequired === 1 ? " is" : "s are"} unmapped.`}
          </CardDescription>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="ghost" size="sm" disabled={!dirty || saving} onClick={() => setRows(initialRows(spec, mapping))}>
            <Undo2 /> Reset
          </Button>
          <Button
            size="sm"
            loading={saving}
            disabled={!dirty}
            onClick={() => void onSave(rows.filter((r) => r.source_column && r.dataset_id))}
          >
            <Save /> Save mapping
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <THead>
            <TR className="hover:bg-transparent">
              <TH>Spec column</TH>
              <TH>File</TH>
              <TH>Your column</TH>
              <TH className="hidden md:table-cell">Transform note</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((r, i) => {
              const sc = specCol(r.spec_column);
              const cols = columnsOf(r.dataset_id);
              const idBase = `map-${i}`;
              return (
                <TR key={r.spec_column}>
                  <TD className="min-w-36">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <code className="text-xs font-medium">{r.spec_column}</code>
                      {sc && <Badge variant="secondary">{sc.type}</Badge>}
                      {sc && !sc.required && <Badge variant="outline">optional</Badge>}
                      {!sc && <Badge variant="warning">not in spec</Badge>}
                    </div>
                  </TD>
                  <TD className="min-w-40">
                    <label htmlFor={`${idBase}-ds`} className="sr-only">
                      File for {r.spec_column}
                    </label>
                    <Select
                      id={`${idBase}-ds`}
                      value={r.dataset_id || ""}
                      onChange={(e) => update(i, { dataset_id: Number(e.target.value) || 0, source_column: "" })}
                    >
                      <option value="">— not mapped —</option>
                      {datasets.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.original_name}
                        </option>
                      ))}
                    </Select>
                  </TD>
                  <TD className="min-w-40">
                    <label htmlFor={`${idBase}-col`} className="sr-only">
                      Column for {r.spec_column}
                    </label>
                    <Select
                      id={`${idBase}-col`}
                      value={r.source_column}
                      disabled={!r.dataset_id}
                      onChange={(e) => update(i, { source_column: e.target.value })}
                    >
                      <option value="">— choose column —</option>
                      {cols.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name} ({c.inferred_type})
                        </option>
                      ))}
                      {r.source_column && !cols.some((c) => c.name === r.source_column) && (
                        <option value={r.source_column}>{r.source_column}</option>
                      )}
                    </Select>
                  </TD>
                  <TD className="hidden min-w-48 md:table-cell">
                    <label htmlFor={`${idBase}-tf`} className="sr-only">
                      Transform note for {r.spec_column}
                    </label>
                    <Input
                      id={`${idBase}-tf`}
                      value={r.transform}
                      onChange={(e) => update(i, { transform: e.target.value })}
                      placeholder="e.g. parse as date dd/mm/yyyy"
                    />
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}
