"use client";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { Results } from "@/lib/types";
import { formatPct, formatValue, toNumber } from "@/lib/format";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/** KPI and model-metric deltas between two runs. */
export function RunCompare({
  current,
  previous,
  currentLabel,
  previousLabel,
}: {
  current: Results;
  previous: Results;
  currentLabel: string;
  previousLabel: string;
}) {
  const prevKpi = new Map(previous.kpis.map((k) => [k.key, k]));
  const rows = current.kpis.map((k) => {
    const p = prevKpi.get(k.key);
    const a = toNumber(k.value);
    const b = toNumber(p?.value);
    const change = a !== null && b !== null && b !== 0 ? (a - b) / Math.abs(b) : null;
    return { key: k.key, label: k.label, cur: formatValue(k.value, k.format, k.unit), prev: p ? formatValue(p.value, p.format, p.unit) : "—", change };
  });
  const metricKeys = Array.from(new Set([...Object.keys(current.model?.metrics ?? {}), ...Object.keys(previous.model?.metrics ?? {})]));
  for (const m of metricKeys) {
    const a = current.model?.metrics?.[m] ?? null;
    const b = previous.model?.metrics?.[m] ?? null;
    rows.push({
      key: `model.${m}`,
      label: `Model ${m}`,
      cur: formatValue(a),
      prev: formatValue(b),
      change: a !== null && b !== null && b !== 0 ? (a - b) / Math.abs(b) : null,
    });
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Compare runs</CardTitle>
        <CardDescription>
          {currentLabel} vs. {previousLabel}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No KPIs to compare.</p>
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Metric</TH>
                <TH className="text-right">{previousLabel}</TH>
                <TH className="text-right">{currentLabel}</TH>
                <TH className="text-right">Change</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((r) => {
                const big = r.change !== null && Math.abs(r.change) > 0.5;
                return (
                  <TR key={r.key}>
                    <TD className="max-w-56 truncate" title={r.label}>
                      {r.label}
                    </TD>
                    <TD className="text-right tabular-nums text-muted-foreground">{r.prev}</TD>
                    <TD className="text-right font-medium tabular-nums">{r.cur}</TD>
                    <TD className={cn("text-right tabular-nums", big && "font-semibold text-warning")}>
                      <span className="inline-flex items-center gap-1">
                        {r.change === null ? (
                          <Minus className="size-3.5 text-muted-foreground" aria-hidden />
                        ) : r.change > 0 ? (
                          <ArrowUpRight className="size-3.5" aria-hidden />
                        ) : r.change < 0 ? (
                          <ArrowDownRight className="size-3.5" aria-hidden />
                        ) : null}
                        {r.change === null ? "—" : `${r.change > 0 ? "+" : ""}${formatPct(r.change)}`}
                      </span>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
