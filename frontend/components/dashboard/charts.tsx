"use client";
import * as React from "react";
import type { Data, Layout, LayoutAxis } from "plotly.js";
import type { Format, Widget } from "@/lib/types";
import { formatValue, plotlyHoverFormat, plotlyTickFormat, truncate } from "@/lib/format";
import { PlotlyChart } from "./PlotlyChart";
import { applyTopN, hasData, tableColumn, toTraces, type Resolved, type XYTrace } from "./resolve";
import { hexToRgba, OTHER_COLOR, sequentialScale, type ChartTheme } from "./theme";
import { WidgetEmpty } from "./WidgetEmpty";

export interface ChartWidgetProps {
  widget: Widget;
  resolved: Resolved;
  onReady: () => void;
}

const LABEL_MAX = 20;
const DATE_LIKE = /^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$/;

/** Truncate long category labels on the axis; hover still shows the full text. */
export function categoryTicks(values: unknown[]): Partial<LayoutAxis> | undefined {
  const strs = values.filter((v) => typeof v === "string") as string[];
  if (!strs.some((s) => s.length > LABEL_MAX && !DATE_LIKE.test(s))) return undefined;
  const uniq = Array.from(new Set(values.map((v) => String(v))));
  return { tickmode: "array", tickvals: uniq, ticktext: uniq.map((s) => truncate(s, LABEL_MAX)) };
}

/** Cell labels with a text colour chosen per cell for contrast against the sequential scale. */
function cellAnnotations(
  x: string[],
  y: string[],
  z: (number | null)[][],
  t: ChartTheme,
  fmt: (v: number) => string,
  size = 11,
): Partial<Layout>["annotations"] {
  const flat = z.flat().filter((v): v is number => v !== null && Number.isFinite(v));
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const out: NonNullable<Partial<Layout>["annotations"]> = [];
  z.forEach((row, i) =>
    row.forEach((v, j) => {
      if (v === null || !Number.isFinite(v)) return;
      const n = max > min ? (v - min) / (max - min) : 0.5;
      // light theme: dark → light scale reversed (high = dark); dark theme: high = light
      const darkText = t.dark ? n > 0.62 : n < 0.45;
      out.push({
        x: x[j],
        y: y[i],
        text: fmt(v),
        showarrow: false,
        font: { size, color: darkText ? "#0f172a" : "#ffffff" },
      });
    }),
  );
  return out;
}

function isDateAxis(values: unknown[]): boolean {
  const vals = values.filter((v) => v !== null && v !== undefined);
  return vals.length > 0 && vals.every((v) => typeof v === "string" && DATE_LIKE.test(v));
}

function axisFormat(format: Format | null | undefined): Partial<LayoutAxis> {
  const tickformat = plotlyTickFormat(format);
  const hoverformat = plotlyHoverFormat(format);
  return { ...(tickformat ? { tickformat } : {}), ...(hoverformat ? { hoverformat } : {}) };
}

function axisTitle(text: string | null | undefined): Partial<LayoutAxis> {
  return text ? { title: { text, standoff: 8 } as LayoutAxis["title"] } : {};
}

function commonLabel(traces: XYTrace[], key: "xLabel" | "yLabel"): string | null {
  const vals = Array.from(new Set(traces.map((t) => t[key]).filter(Boolean)));
  return vals.length === 1 ? (vals[0] as string) : null;
}

function colorFor(i: number, t: ChartTheme, trace?: XYTrace) {
  if (trace?.key === "__other__") return OTHER_COLOR;
  return t.palette[i % t.palette.length];
}

function useStableBuild(build: (t: ChartTheme) => { data: Data[]; layout?: Partial<Layout> }, deps: React.DependencyList) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return React.useCallback(build, deps);
}

function EmptyChart({ onReady, message }: { onReady: () => void; message?: string }) {
  React.useEffect(() => onReady(), [onReady]);
  return <WidgetEmpty message={message} />;
}

/* ------------------------------------------------------------------ */
/* line                                                                */
/* ------------------------------------------------------------------ */

export function LineChartWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const traces = React.useMemo(() => applyTopN(toTraces(resolved, widget.binding), widget.binding.top_n), [resolved, widget.binding]);
  const fmt = widget.format ?? traces[0]?.format;
  const build = useStableBuild(
    (t) => {
      const data: Data[] = traces.map((tr, i) => {
        const color = colorFor(i, t, tr);
        if (tr.kind === "bar") return { type: "bar", name: tr.name, x: tr.x, y: tr.y, marker: { color } } as Data;
        const points = tr.x.length;
        return {
          type: "scatter",
          mode: points <= 40 ? "lines+markers" : "lines",
          name: tr.name,
          x: tr.x,
          y: tr.y,
          line: { color, width: 2, dash: tr.isForecast ? "dash" : "solid", shape: "linear" },
          marker: { size: 5, color },
          fill: tr.kind === "area" ? (i === 0 ? "tozeroy" : "tonexty") : undefined,
          fillcolor: tr.kind === "area" ? hexToRgba(color, 0.15) : undefined,
          connectgaps: false,
        } as Data;
      });
      return {
        data,
        layout: {
          showlegend: traces.length > 1,
          hovermode: "x unified",
          xaxis: { ...axisTitle(widget.x_label ?? commonLabel(traces, "xLabel")), ...categoryTicks(traces[0]?.x ?? []) },
          yaxis: { ...axisTitle(widget.y_label ?? commonLabel(traces, "yLabel")), ...axisFormat(fmt) },
        },
      };
    },
    [traces, widget.x_label, widget.y_label, fmt],
  );
  if (!hasData(traces)) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* bar (vertical / horizontal, stacked, top_n with "Other")            */
/* ------------------------------------------------------------------ */

export function BarChartWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const traces = React.useMemo(() => applyTopN(toTraces(resolved, widget.binding), widget.binding.top_n), [resolved, widget.binding]);
  const horizontal = widget.orientation === "horizontal";
  const fmt = widget.format ?? traces[0]?.format;
  const build = useStableBuild(
    (t) => {
      const single = traces.length === 1;
      const data: Data[] = traces.map((tr, i) => {
        const colors = single
          ? tr.x.map((x) => (typeof x === "string" && x.startsWith("Other (") ? OTHER_COLOR : colorFor(0, t)))
          : colorFor(i, t, tr);
        const fullCats = tr.x.map((v) => String(v));
        return {
          type: "bar",
          name: tr.name,
          orientation: horizontal ? "h" : "v",
          x: horizontal ? tr.y : tr.x,
          y: horizontal ? tr.x : tr.y,
          marker: { color: colors },
          customdata: fullCats,
          hovertemplate: `%{customdata}<br>${single ? "" : `${tr.name}: `}%{${horizontal ? "x" : "y"}}<extra></extra>`,
        } as Data;
      });
      const catAxis: Partial<LayoutAxis> = {
        ...axisTitle(horizontal ? widget.y_label : (widget.x_label ?? commonLabel(traces, "xLabel"))),
        ...categoryTicks(traces[0]?.x ?? []),
        ...(horizontal ? { autorange: "reversed" as const } : {}),
        type: isDateAxis(traces[0]?.x ?? []) ? "date" : "category",
      };
      const valAxis: Partial<LayoutAxis> = {
        ...axisTitle(horizontal ? widget.x_label : (widget.y_label ?? commonLabel(traces, "yLabel"))),
        ...axisFormat(fmt),
      };
      return {
        data,
        layout: {
          barmode: widget.stacked ? "stack" : "group",
          bargap: 0.25,
          showlegend: traces.length > 1,
          xaxis: horizontal ? valAxis : catAxis,
          yaxis: horizontal ? catAxis : valAxis,
        },
      };
    },
    [traces, horizontal, widget.stacked, widget.x_label, widget.y_label, fmt],
  );
  if (!hasData(traces)) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* scatter                                                             */
/* ------------------------------------------------------------------ */

export function ScatterChartWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const traces = React.useMemo(() => toTraces(resolved, widget.binding), [resolved, widget.binding]);
  const fmt = widget.format ?? traces[0]?.format;
  const build = useStableBuild(
    (t) => ({
      data: traces.map(
        (tr, i) =>
          ({
            type: tr.x.length > 2000 ? "scattergl" : "scatter",
            mode: "markers",
            name: tr.name,
            x: tr.x,
            y: tr.y,
            marker: { color: hexToRgba(colorFor(i, t, tr), 0.7), size: 7, line: { width: 0 } },
          }) as Data,
      ),
      layout: {
        showlegend: traces.length > 1,
        xaxis: { ...axisTitle(widget.x_label ?? commonLabel(traces, "xLabel")), ...categoryTicks(traces[0]?.x ?? []) },
        yaxis: { ...axisTitle(widget.y_label ?? commonLabel(traces, "yLabel")), ...axisFormat(fmt) },
      },
    }),
    [traces, widget.x_label, widget.y_label, fmt],
  );
  if (!hasData(traces)) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* histogram                                                           */
/* ------------------------------------------------------------------ */

/**
 * Series-backed histograms are treated as pre-binned (x = bin labels, y = counts);
 * table-backed histograms bin the raw values of y_columns[0] (or x_column) client-side.
 */
export function HistogramWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const raw = React.useMemo(() => {
    if (resolved.source !== "tables" || !resolved.table) return null;
    const t = resolved.table;
    const col = widget.binding.y_columns?.[0] ?? widget.binding.x_column ?? t.columns.find((c) => t.column_formats?.[c] !== "text") ?? t.columns[0];
    return { col, values: tableColumn(t, col), format: t.column_formats?.[col] ?? "number" };
  }, [resolved, widget.binding]);
  const traces = React.useMemo(() => (raw ? [] : toTraces(resolved, widget.binding)), [raw, resolved, widget.binding]);
  const fmt = widget.format ?? raw?.format ?? traces[0]?.format;

  const build = useStableBuild(
    (t) => {
      if (raw) {
        return {
          data: [
            {
              type: "histogram",
              x: raw.values,
              name: raw.col,
              marker: { color: colorFor(0, t), line: { color: t.dark ? "#121a2e" : "#ffffff", width: 1 } },
              hovertemplate: "%{x}<br>Count: %{y}<extra></extra>",
            } as Data,
          ],
          layout: {
            bargap: 0.04,
            showlegend: false,
            xaxis: { ...axisTitle(widget.x_label ?? raw.col), ...axisFormat(fmt) },
            yaxis: { ...axisTitle(widget.y_label ?? "Count"), tickformat: ",d" },
          },
        };
      }
      return {
        data: traces.map(
          (tr, i) =>
            ({
              type: "bar",
              name: tr.name,
              x: tr.x,
              y: tr.y,
              marker: { color: colorFor(i, t, tr), line: { color: t.dark ? "#121a2e" : "#ffffff", width: 1 } },
            }) as Data,
        ),
        layout: {
          bargap: 0.02,
          barmode: "overlay",
          showlegend: traces.length > 1,
          xaxis: { ...axisTitle(widget.x_label ?? commonLabel(traces, "xLabel")), ...categoryTicks(traces[0]?.x ?? []) },
          yaxis: { ...axisTitle(widget.y_label ?? commonLabel(traces, "yLabel") ?? "Count"), ...axisFormat(fmt ?? "integer") },
        },
      };
    },
    [raw, traces, widget.x_label, widget.y_label, fmt],
  );
  const empty = raw ? raw.values.length === 0 : !hasData(traces);
  if (empty) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* heatmap                                                             */
/* ------------------------------------------------------------------ */

interface Matrix {
  x: string[];
  y: string[];
  z: (number | null)[][];
  format: Format;
}

function toMatrix(widget: Widget, resolved: Resolved): Matrix | null {
  if (resolved.source === "tables" && resolved.table) {
    const t = resolved.table;
    const rowCol = widget.binding.x_column && t.columns.includes(widget.binding.x_column) ? widget.binding.x_column : t.columns[0];
    const valueCols = widget.binding.y_columns?.length
      ? widget.binding.y_columns.filter((c) => t.columns.includes(c))
      : t.columns.filter((c) => c !== rowCol);
    const ri = t.columns.indexOf(rowCol);
    return {
      x: valueCols,
      y: t.rows.map((r) => String(r[ri] ?? "")),
      z: t.rows.map((r) => valueCols.map((c) => {
        const v = r[t.columns.indexOf(c)];
        return typeof v === "number" ? v : v === null || v === undefined || v === "" ? null : Number(v);
      })),
      format: widget.format ?? t.column_formats?.[valueCols[0]] ?? "number",
    };
  }
  const traces = toTraces(resolved, widget.binding);
  if (!traces.length) return null;
  return {
    x: traces[0].x.map(String),
    y: traces.map((t) => t.name),
    z: traces.map((t) => t.y),
    format: widget.format ?? traces[0].format,
  };
}

export function HeatmapWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const m = React.useMemo(() => toMatrix(widget, resolved), [widget, resolved]);
  const build = useStableBuild(
    (t) => {
      if (!m) return { data: [] };
      const cells = m.x.length * m.y.length;
      const hover = plotlyHoverFormat(m.format);
      return {
        data: [
          {
            type: "heatmap",
            x: m.x,
            y: m.y,
            z: m.z,
            colorscale: sequentialScale(t.dark),
            showscale: true,
            colorbar: { thickness: 10, outlinewidth: 0, tickfont: { size: 11, color: t.muted }, tickformat: plotlyTickFormat(m.format) },
            hovertemplate: `%{y} × %{x}<br>%{z${hover ? `:${hover}` : ""}}<extra></extra>`,
            xgap: 1,
            ygap: 1,
          } as Data,
        ],
        layout: {
          annotations: cells <= 150 ? cellAnnotations(m.x, m.y, m.z, t, (v) => formatValue(v, m.format)) : [],
          xaxis: { ...axisTitle(widget.x_label), ...categoryTicks(m.x), showgrid: false, type: "category" },
          yaxis: { ...axisTitle(widget.y_label), ...categoryTicks(m.y), showgrid: false, autorange: "reversed", type: "category" },
        },
      };
    },
    [m, widget.x_label, widget.y_label],
  );
  if (!m || !m.z.some((r) => r.some((v) => v !== null && Number.isFinite(v)))) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* pie (donut; > 6 slices grouped into "Other")                        */
/* ------------------------------------------------------------------ */

export function PieChartWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const trace = React.useMemo(() => {
    const tr = toTraces(resolved, widget.binding)[0];
    if (!tr) return null;
    return applyTopN([tr], widget.binding.top_n ?? (tr.x.length > 6 ? 5 : null))[0];
  }, [resolved, widget.binding]);
  const build = useStableBuild(
    (t) => {
      if (!trace) return { data: [] };
      const labels = trace.x.map(String);
      const colors = labels.map((l, i) => (l.startsWith("Other (") ? OTHER_COLOR : t.palette[i % t.palette.length]));
      return {
        data: [
          {
            type: "pie",
            labels,
            values: trace.y,
            hole: 0.55,
            sort: false,
            direction: "clockwise",
            marker: { colors, line: { color: t.dark ? "#121a2e" : "#ffffff", width: 2 } },
            textinfo: "percent",
            textposition: "inside",
            insidetextorientation: "horizontal",
            textfont: { size: 11 },
            hovertemplate: `%{label}<br>%{value}<br>%{percent}<extra></extra>`,
            automargin: true,
          } as Data,
        ],
        layout: {
          showlegend: true,
          uniformtext: { minsize: 11, mode: "hide" },
          // legend below the donut: works from 390px phones to wide cards
          legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.02, yanchor: "top" },
          margin: { l: 8, r: 8, t: 8, b: 8 },
        },
      };
    },
    [trace],
  );
  if (!trace || !hasData([trace])) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* feature_importance (horizontal bar, sorted)                          */
/* ------------------------------------------------------------------ */

export function FeatureImportanceWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const items = React.useMemo(() => {
    let pairs: { feature: string; importance: number }[] = [];
    if (resolved.source === "model" && resolved.model?.feature_importance?.length) {
      pairs = resolved.model.feature_importance.map((f) => ({ feature: f.feature, importance: f.importance }));
    } else {
      const tr = toTraces(resolved, widget.binding)[0];
      if (tr) pairs = tr.x.map((x, i) => ({ feature: String(x), importance: tr.y[i] ?? 0 }));
    }
    pairs = pairs.filter((p) => Number.isFinite(p.importance)).sort((a, b) => b.importance - a.importance);
    return pairs.slice(0, widget.binding.top_n ?? 15);
  }, [resolved, widget.binding]);
  const build = useStableBuild(
    (t) => {
      const labels = items.map((p) => p.feature);
      return {
        data: [
          {
            type: "bar",
            orientation: "h",
            y: labels,
            x: items.map((p) => p.importance),
            marker: { color: colorFor(0, t) },
            customdata: labels,
            hovertemplate: "%{customdata}<br>Importance: %{x:.4~g}<extra></extra>",
          } as Data,
        ],
        layout: {
          showlegend: false,
          bargap: 0.3,
          xaxis: { ...axisTitle(widget.x_label ?? "Importance"), ...axisFormat(widget.format) },
          yaxis: { ...categoryTicks(labels), autorange: "reversed", type: "category", ...axisTitle(widget.y_label) },
        },
      };
    },
    [items, widget.x_label, widget.y_label, widget.format],
  );
  if (!items.length) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* confusion_matrix                                                    */
/* ------------------------------------------------------------------ */

export function ConfusionMatrixWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const cm = React.useMemo(() => {
    const m = resolved.source === "model" ? resolved.model : null;
    if (!m?.confusion_matrix?.length) return null;
    const n = m.confusion_matrix.length;
    const labels = m.class_labels?.length === n ? m.class_labels : Array.from({ length: n }, (_, i) => `Class ${i}`);
    const rowTotals = m.confusion_matrix.map((r) => r.reduce((a, b) => a + b, 0));
    const pct = m.confusion_matrix.map((r, i) => r.map((v) => (rowTotals[i] ? v / rowTotals[i] : 0)));
    return { z: m.confusion_matrix, labels: labels.map(String), pct };
  }, [resolved]);
  const build = useStableBuild(
    (t) => {
      if (!cm) return { data: [] };
      return {
        data: [
          {
            type: "heatmap",
            x: cm.labels,
            y: cm.labels,
            z: cm.z,
            customdata: cm.pct,
            colorscale: sequentialScale(t.dark),
            showscale: false,
            hovertemplate: "Actual: %{y}<br>Predicted: %{x}<br>Count: %{z:,d}<br>Row share: %{customdata:.1%}<extra></extra>",
            xgap: 2,
            ygap: 2,
          } as Data,
        ],
        layout: {
          annotations: cellAnnotations(cm.labels, cm.labels, cm.z, t, (v) => Math.round(v).toLocaleString(), 12),
          xaxis: { ...axisTitle(widget.x_label ?? "Predicted"), ...categoryTicks(cm.labels), type: "category", showgrid: false, side: "bottom" },
          yaxis: { ...axisTitle(widget.y_label ?? "Actual"), ...categoryTicks(cm.labels), type: "category", showgrid: false, autorange: "reversed" },
        },
      };
    },
    [cm, widget.x_label, widget.y_label],
  );
  if (!cm) return <EmptyChart onReady={onReady} message="No confusion matrix in the results." />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}

/* ------------------------------------------------------------------ */
/* forecast_with_interval                                              */
/* ------------------------------------------------------------------ */

export function ForecastWidget({ widget, resolved, onReady }: ChartWidgetProps) {
  const traces = React.useMemo(() => toTraces(resolved, widget.binding), [resolved, widget.binding]);
  const fmt = widget.format ?? traces[0]?.format;
  const build = useStableBuild(
    (t) => {
      // Same colour per group (actual + forecast of one metric), otherwise per series.
      const groups = Array.from(new Set(traces.map((tr, i) => tr.group ?? `__${i}`)));
      const data: Data[] = [];
      traces.forEach((tr, i) => {
        const color = t.palette[groups.indexOf(tr.group ?? `__${i}`) % t.palette.length];
        if (tr.lower && tr.upper) {
          data.push({
            type: "scatter",
            mode: "lines",
            x: tr.x,
            y: tr.upper,
            line: { width: 0, color },
            hoverinfo: "skip",
            showlegend: false,
            name: `${tr.name} upper`,
          } as Data);
          data.push({
            type: "scatter",
            mode: "lines",
            x: tr.x,
            y: tr.lower,
            line: { width: 0, color },
            fill: "tonexty",
            fillcolor: hexToRgba(color, t.dark ? 0.25 : 0.18),
            hoverinfo: "skip",
            name: "Interval",
            showlegend: i === traces.findIndex((x) => x.lower && x.upper),
          } as Data);
        }
        data.push({
          type: "scatter",
          mode: tr.x.length <= 40 ? "lines+markers" : "lines",
          name: tr.name,
          x: tr.x,
          y: tr.y,
          line: { color, width: 2, dash: tr.isForecast ? "dash" : "solid" },
          marker: { size: 4, color },
          customdata: tr.lower && tr.upper ? tr.x.map((_, j) => [tr.lower?.[j] ?? null, tr.upper?.[j] ?? null]) : undefined,
          hovertemplate:
            tr.lower && tr.upper
              ? `${tr.name}: %{y${plotlyHoverFormat(fmt) ? `:${plotlyHoverFormat(fmt)}` : ""}}<br>Interval: %{customdata[0]${plotlyHoverFormat(fmt) ? `:${plotlyHoverFormat(fmt)}` : ""}} – %{customdata[1]${plotlyHoverFormat(fmt) ? `:${plotlyHoverFormat(fmt)}` : ""}}<extra></extra>`
              : undefined,
        } as Data);
      });
      return {
        data,
        layout: {
          showlegend: true,
          hovermode: "x unified",
          xaxis: { ...axisTitle(widget.x_label ?? commonLabel(traces, "xLabel")) },
          yaxis: { ...axisTitle(widget.y_label ?? commonLabel(traces, "yLabel")), ...axisFormat(fmt) },
        },
      };
    },
    [traces, widget.x_label, widget.y_label, fmt],
  );
  if (!hasData(traces)) return <EmptyChart onReady={onReady} />;
  return <PlotlyChart build={build} onReady={onReady} ariaLabel={widget.title} />;
}


