/**
 * Resolve a widget Binding against results.json (PLAN §7) and turn it into chart-ready shapes.
 */
import type {
  Binding,
  Filter,
  Format,
  KPI,
  ModelInfo,
  Results,
  Series,
  StatTest,
  Table,
} from "@/lib/types";
import { toNumber } from "@/lib/format";

export type FilterValues = Record<string, string>; // filter id -> selected value ("" = all)

export type Resolved =
  | { source: "kpis"; kpis: KPI[] }
  | { source: "series"; series: Series[] }
  | { source: "tables"; table: Table | null; tables: Table[] }
  | { source: "model"; model: ModelInfo | null; keys: string[] }
  | { source: "stat_tests"; tests: StatTest[] }
  | { source: "insights"; insights: string[] };

function pick<T extends { key: string }>(items: T[] | undefined, keys: string[]): T[] {
  const list = items ?? [];
  if (!keys.length) return list;
  const byKey = new Map(list.map((i) => [i.key, i]));
  return keys.map((k) => byKey.get(k)).filter((x): x is T => !!x);
}

/** Apply dashboard filters that target this table. */
export function filterTable(table: Table, filters?: Filter[], values?: FilterValues): Table {
  if (!filters?.length || !values) return table;
  let rows = table.rows;
  for (const f of filters) {
    const v = values[f.id];
    if (!v || f.table_key !== table.key) continue;
    const idx = table.columns.indexOf(f.column);
    if (idx < 0) continue;
    rows = rows.filter((r) => String(r[idx] ?? "") === v);
  }
  return rows === table.rows ? table : { ...table, rows };
}

export function resolveBinding(
  results: Results,
  binding: Binding,
  filters?: Filter[],
  values?: FilterValues,
): Resolved {
  const keys = binding.keys ?? [];
  switch (binding.source) {
    case "kpis":
      return { source: "kpis", kpis: pick(results.kpis, keys) };
    case "series":
      return { source: "series", series: pick(results.series, keys) };
    case "tables": {
      const tables = pick(results.tables, keys).map((t) => filterTable(t, filters, values));
      return { source: "tables", table: tables[0] ?? null, tables };
    }
    case "model":
      return { source: "model", model: results.model ?? null, keys };
    case "stat_tests":
      return { source: "stat_tests", tests: pick(results.stat_tests, keys) };
    case "insights": {
      const all = results.insights_raw ?? [];
      // keys may be indices ("0", "2") to choose specific insights
      const idx = keys.map((k) => Number(k)).filter((n) => Number.isInteger(n) && n >= 0 && n < all.length);
      return { source: "insights", insights: idx.length ? idx.map((i) => all[i]) : all };
    }
    default:
      return { source: "insights", insights: [] };
  }
}

/* ------------------------------------------------------------------ */
/* Normalised XY traces                                                */
/* ------------------------------------------------------------------ */

export interface XYTrace {
  key: string;
  name: string;
  x: unknown[];
  y: (number | null)[];
  format: Format;
  kind?: Series["kind"];
  isForecast?: boolean;
  lower?: (number | null)[] | null;
  upper?: (number | null)[] | null;
  group?: string | null;
  xLabel?: string | null;
  yLabel?: string | null;
}

function numericColumns(t: Table, exclude: string[] = []): string[] {
  return t.columns.filter((c, i) => {
    if (exclude.includes(c)) return false;
    const fmt = t.column_formats?.[c];
    if (fmt === "text" || fmt === "date") return false;
    const sample = t.rows.slice(0, 50).map((r) => r[i]).filter((v) => v !== null && v !== undefined && v !== "");
    return sample.length > 0 && sample.every((v) => toNumber(v) !== null);
  });
}

export function tableColumn(t: Table, col: string): unknown[] {
  const i = t.columns.indexOf(col);
  return i < 0 ? [] : t.rows.map((r) => r[i]);
}

/** Convert a table into traces: x = x_column (default first column), one trace per y column. */
export function tableToTraces(t: Table, binding: Binding): XYTrace[] {
  const xCol = binding.x_column && t.columns.includes(binding.x_column) ? binding.x_column : t.columns[0];
  const yCols = (binding.y_columns?.length ? binding.y_columns.filter((c) => t.columns.includes(c)) : numericColumns(t, [xCol])) ?? [];
  const x = tableColumn(t, xCol);
  return yCols.map((c) => ({
    key: `${t.key}.${c}`,
    name: c,
    x,
    y: tableColumn(t, c).map(toNumber),
    format: t.column_formats?.[c] ?? "number",
    xLabel: xCol,
    yLabel: c,
  }));
}

/** Everything chart-like a binding can produce, as XY traces. */
export function toTraces(r: Resolved, binding: Binding): XYTrace[] {
  switch (r.source) {
    case "series":
      return r.series.map((s) => ({
        key: s.key,
        name: s.label ?? s.key,
        x: s.x ?? [],
        y: (s.y ?? []).map((v) => toNumber(v)),
        format: s.format ?? "number",
        kind: s.kind,
        isForecast: s.is_forecast,
        lower: s.y_lower,
        upper: s.y_upper,
        group: s.group,
        xLabel: s.x_label,
        yLabel: s.y_label,
      }));
    case "tables":
      return r.table ? tableToTraces(r.table, binding) : [];
    case "kpis": {
      const numeric = r.kpis.filter((k) => toNumber(k.value) !== null);
      if (!numeric.length) return [];
      return [
        {
          key: "kpis",
          name: "Value",
          x: numeric.map((k) => k.label),
          y: numeric.map((k) => toNumber(k.value)),
          format: numeric[0].format,
        },
      ];
    }
    case "model": {
      const m = r.model;
      if (!m) return [];
      if (m.feature_importance?.length) {
        return [
          {
            key: "feature_importance",
            name: "Importance",
            x: m.feature_importance.map((f) => f.feature),
            y: m.feature_importance.map((f) => f.importance),
            format: "number",
          },
        ];
      }
      const metrics = Object.entries(m.metrics ?? {}).filter(([k]) => !r.keys.length || r.keys.includes(k));
      return [
        { key: "metrics", name: "Model", x: metrics.map(([k]) => k), y: metrics.map(([, v]) => v), format: "number" },
      ];
    }
    case "stat_tests":
      return r.tests.length
        ? [{ key: "stat_tests", name: "Statistic", x: r.tests.map((t) => t.key), y: r.tests.map((t) => t.statistic), format: "number" }]
        : [];
    default:
      return [];
  }
}

export function hasData(traces: XYTrace[]): boolean {
  return traces.some((t) => t.y.some((v) => v !== null && Number.isFinite(v)));
}

const sum = (ys: (number | null)[]) => ys.reduce<number>((a, b) => a + (b ?? 0), 0);

/**
 * top_n: with one trace keep the N largest categories and sum the rest into "Other"
 * (mean for percent-formatted values);
 * with several traces keep the N largest series and sum the rest into an "Other" series.
 */
export function applyTopN(traces: XYTrace[], topN: number | null | undefined): XYTrace[] {
  if (!topN || topN < 1) return traces;
  if (traces.length > 1) {
    if (traces.length <= topN) return traces;
    const ranked = [...traces].sort((a, b) => sum(b.y) - sum(a.y));
    const keep = ranked.slice(0, topN);
    const rest = ranked.slice(topN);
    const base = rest[0];
    const sameX = rest.every((t) => t.x.length === base.x.length && t.x.every((v, i) => v === base.x[i]));
    if (!sameX) return keep;
    const other: XYTrace = {
      ...base,
      key: "__other__",
      name: `Other (${rest.length})`,
      y: base.x.map((_, i) => rest.reduce((a, t) => a + (t.y[i] ?? 0), 0)),
      lower: null,
      upper: null,
    };
    return [...keep, other];
  }
  const t = traces[0];
  if (!t || t.x.length <= topN) return traces;
  const idx = t.x.map((_, i) => i).sort((a, b) => (t.y[b] ?? -Infinity) - (t.y[a] ?? -Infinity));
  const keep = idx.slice(0, topN);
  const rest = idx.slice(topN);
  // Rates/percentages are not additive: "Other" gets their mean instead of their sum.
  const restVals = rest.map((i) => t.y[i]).filter((v): v is number => v !== null && Number.isFinite(v));
  const restSum = restVals.reduce((a, b) => a + b, 0);
  const other = t.format === "percent" ? (restVals.length ? restSum / restVals.length : null) : restSum;
  return [
    {
      ...t,
      x: [...keep.map((i) => t.x[i]), `Other (${rest.length})`],
      y: [...keep.map((i) => t.y[i]), other],
    },
  ];
}

/** Collect the distinct values for a filter from its table. */
export function filterOptions(results: Results, f: Filter): string[] {
  const t = results.tables?.find((x) => x.key === f.table_key);
  if (!t) return [];
  const vals = new Set(tableColumn(t, f.column).map((v) => String(v ?? "")).filter(Boolean));
  return Array.from(vals).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** Convert stat tests / KPIs / feature importances into a Table for the table widget. */
export function resolvedToTable(r: Resolved): Table | null {
  switch (r.source) {
    case "tables":
      return r.table;
    case "stat_tests":
      return {
        key: "stat_tests",
        label: "Statistical tests",
        columns: ["key", "test", "statistic", "p_value", "n", "conclusion"],
        rows: r.tests.map((t) => [t.key, t.test, t.statistic, t.p_value, t.n, t.conclusion]),
        column_formats: { statistic: "number", p_value: "number", n: "integer", key: "text", test: "text", conclusion: "text" },
      };
    case "kpis":
      return {
        key: "kpis",
        label: "KPIs",
        columns: ["KPI", "Value"],
        rows: r.kpis.map((k) => [k.label, k.value]),
        column_formats: { KPI: "text" },
      };
    case "model": {
      const m = r.model;
      if (!m) return null;
      if (m.feature_importance?.length) {
        return {
          key: "feature_importance",
          label: "Feature importance",
          columns: ["feature", "importance"],
          rows: m.feature_importance.map((f) => [f.feature, f.importance]),
          column_formats: { feature: "text", importance: "number" },
        };
      }
      const metrics = Object.entries(m.metrics ?? {});
      return {
        key: "metrics",
        label: "Model metrics",
        columns: ["metric", "model", "baseline"],
        rows: metrics.map(([k, v]) => [k, v, m.baseline_metrics?.[k] ?? null]),
        column_formats: { metric: "text", model: "number", baseline: "number" },
      };
    }
    case "series": {
      const s = r.series[0];
      if (!s) return null;
      const cols = [s.x_label ?? "x", ...r.series.map((x) => x.label ?? x.key)];
      return {
        key: s.key,
        label: s.label,
        columns: cols,
        rows: s.x.map((xv, i) => [xv, ...r.series.map((x) => x.y[i] ?? null)]),
        column_formats: {},
      };
    }
    case "insights":
      return null;
  }
}
