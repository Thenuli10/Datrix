"use client";
import * as React from "react";
import { formatValue, humanize, toNumber } from "@/lib/format";
import type { Format, Widget } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { Resolved } from "./resolve";
import { WidgetEmpty } from "./WidgetEmpty";

interface KpiItem {
  key: string;
  label: string;
  value: number | string | null;
  format: Format;
  unit: string | null;
  description: string | null;
  baseline?: number | null;
}

function toItems(widget: Widget, r: Resolved): KpiItem[] {
  switch (r.source) {
    case "kpis":
      return r.kpis.map((k) => ({
        key: k.key,
        label: k.label,
        value: k.value,
        format: widget.format ?? k.format ?? "number",
        unit: k.unit,
        description: k.description,
      }));
    case "model": {
      const m = r.model;
      if (!m) return [];
      const keys = r.keys.length ? r.keys : Object.keys(m.metrics ?? {});
      return keys
        .filter((k) => k in (m.metrics ?? {}))
        .map((k) => ({
          key: k,
          label: humanize(k).toUpperCase().length <= 4 ? k.toUpperCase() : humanize(k),
          value: m.metrics[k],
          format: widget.format ?? "number",
          unit: null,
          description: null,
          baseline: m.baseline_metrics?.[k] ?? null,
        }));
    }
    case "stat_tests":
      return r.tests.map((t) => ({
        key: t.key,
        label: `${t.test} p-value`,
        value: t.p_value,
        format: widget.format ?? "number",
        unit: null,
        description: t.conclusion,
      }));
    case "series":
      // Latest value of each series
      return r.series.map((s) => ({
        key: s.key,
        label: s.label ?? s.key,
        value: [...(s.y ?? [])].reverse().find((v) => v !== null) ?? null,
        format: widget.format ?? s.format ?? "number",
        unit: null,
        description: null,
      }));
    default:
      return [];
  }
}

export function KpiWidget({ widget, resolved, onReady }: { widget: Widget; resolved: Resolved; onReady: () => void }) {
  React.useEffect(() => onReady(), [onReady]);
  const items = React.useMemo(() => toItems(widget, resolved), [widget, resolved]);
  if (!items.length) return <WidgetEmpty />;
  const single = items.length === 1;
  return (
    <div className="@container h-full min-h-0">
    <div
      className={cn(
        "grid h-full min-h-0 gap-3",
        single
          ? "grid-cols-1"
          : "grid-cols-2 content-center gap-y-2 overflow-auto @md:grid-cols-3 @2xl:grid-cols-4 @4xl:grid-cols-6",
      )}
    >
      {items.map((k) => {
        const text = formatValue(k.value, k.format, k.unit);
        const v = toNumber(k.value);
        const delta = v !== null && k.baseline !== null && k.baseline !== undefined ? v - k.baseline : null;
        return (
          <div key={k.key} className="flex min-w-0 flex-col justify-center">
            {!single && (
              <div className="truncate text-xs font-medium text-muted-foreground" title={k.label}>
                {k.label}
              </div>
            )}
            <div
              className={cn("truncate font-semibold tabular-nums tracking-tight", single ? "text-3xl" : "text-lg leading-tight")}
              title={`${k.label}: ${text}`}
            >
              {text}
            </div>
            {delta !== null && (
              <div className="truncate text-xs text-muted-foreground" title="Compared with the simple baseline">
                Baseline {formatValue(k.baseline, k.format)} ·{" "}
                <span className={delta >= 0 ? "text-success" : "text-destructive"}>
                  {delta >= 0 ? "+" : ""}
                  {formatValue(delta, k.format)}
                </span>
              </div>
            )}
            {k.description && single && (
              <div className="line-clamp-2 text-xs text-muted-foreground" title={k.description}>
                {k.description}
              </div>
            )}
          </div>
        );
      })}
    </div>
    </div>
  );
}
