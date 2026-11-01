"use client";
import * as React from "react";
import { Filter as FilterIcon, X } from "lucide-react";
import type { DashboardSpec, Results, Widget } from "@/lib/types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select } from "@/components/ui/select";
import { Markdown } from "@/components/layout/common";
import { cn } from "@/lib/utils";
import {
  BarChartWidget,
  ConfusionMatrixWidget,
  FeatureImportanceWidget,
  ForecastWidget,
  HeatmapWidget,
  HistogramWidget,
  LineChartWidget,
  PieChartWidget,
  ScatterChartWidget,
} from "./charts";
import { KpiWidget } from "./KpiWidget";
import { TableWidget } from "./TableWidget";
import { WidgetEmpty } from "./WidgetEmpty";
import { filterOptions, resolveBinding, type FilterValues, type Resolved } from "./resolve";

type WidgetProps = { widget: Widget; resolved: Resolved; onReady: () => void };

function TextInsightWidget({ widget, resolved, onReady }: WidgetProps) {
  React.useEffect(() => onReady(), [onReady]);
  const body =
    widget.text ??
    (resolved.source === "insights" && resolved.insights.length ? resolved.insights.map((i) => `- ${i}`).join("\n") : "");
  if (!body) return <WidgetEmpty message="No insight text." />;
  return (
    <div className="h-full overflow-auto pr-1">
      <Markdown>{body}</Markdown>
    </div>
  );
}

const COMPONENTS: Record<Widget["type"], React.ComponentType<WidgetProps>> = {
  kpi: KpiWidget,
  line: LineChartWidget,
  bar: BarChartWidget,
  scatter: ScatterChartWidget,
  histogram: HistogramWidget,
  heatmap: HeatmapWidget,
  pie: PieChartWidget,
  table: TableWidget,
  feature_importance: FeatureImportanceWidget,
  confusion_matrix: ConfusionMatrixWidget,
  forecast_with_interval: ForecastWidget,
  text_insight: TextInsightWidget,
};

/** Minimum stacked height (grid rows) on small screens so charts stay readable. */
const MOBILE_MIN_ROWS: Partial<Record<Widget["type"], number>> = {
  kpi: 1,
  text_insight: 2,
  table: 5,
};

function WidgetCard({
  widget,
  results,
  filterValues,
  spec,
  onReady,
}: {
  widget: Widget;
  results: Results;
  spec: DashboardSpec;
  filterValues: FilterValues;
  onReady: (id: string) => void;
}) {
  const resolved = React.useMemo(
    () => resolveBinding(results, widget.binding, spec.filters, filterValues),
    [results, widget.binding, spec.filters, filterValues],
  );
  const ready = React.useCallback(() => onReady(widget.id), [onReady, widget.id]);
  const Comp = COMPONENTS[widget.type];
  const { x, y, w, h } = widget.layout;
  const isKpi = widget.type === "kpi";
  const mobileRows = Math.max(h, MOBILE_MIN_ROWS[widget.type] ?? 3);
  const style = {
    "--gc": `${Math.min(x, 11) + 1} / span ${Math.min(w, 12 - Math.min(x, 11))}`,
    "--gr": `${y + 1} / span ${h}`,
    "--h": mobileRows,
  } as React.CSSProperties;

  return (
    <section
      data-widget-id={widget.id}
      data-widget-type={widget.type}
      aria-label={widget.title}
      style={style}
      className={cn(
        "dash-cell flex flex-col overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm",
        isKpi ? "p-4" : "p-4 pb-3",
      )}
    >
      <header className={cn("min-w-0", isKpi ? "mb-1" : "mb-2")}>
        <h3
          className={cn("truncate font-medium", isKpi ? "text-xs text-muted-foreground" : "text-sm")}
          title={widget.title}
        >
          {widget.title}
        </h3>
        {widget.subtitle && !isKpi && (
          <p className="truncate text-xs text-muted-foreground" title={widget.subtitle}>
            {widget.subtitle}
          </p>
        )}
      </header>
      <div className="min-h-0 flex-1">
        {Comp ? <Comp widget={widget} resolved={resolved} onReady={ready} /> : <WidgetEmpty message={`Unknown widget type "${widget.type}"`} />}
      </div>
    </section>
  );
}

function Grid({
  widgets,
  ...rest
}: {
  widgets: Widget[];
  results: Results;
  spec: DashboardSpec;
  filterValues: FilterValues;
  onReady: (id: string) => void;
}) {
  // DOM order = reading order (used when stacked on mobile).
  const sorted = React.useMemo(
    () => [...widgets].sort((a, b) => a.layout.y - b.layout.y || a.layout.x - b.layout.x),
    [widgets],
  );
  if (!sorted.length) return <WidgetEmpty message="No widgets on this tab." />;
  return (
    <div className="dash-grid">
      {sorted.map((w) => (
        <WidgetCard key={w.id} widget={w} {...rest} />
      ))}
    </div>
  );
}

export interface SpecRendererProps {
  spec: DashboardSpec;
  results: Results;
  /** Render every tab stacked (used by the bare /render page for screenshots). */
  allTabs?: boolean;
  /** Called once every rendered widget has drawn. */
  onReady?: () => void;
  className?: string;
}

export function SpecRenderer({ spec, results, allTabs = false, onReady, className }: SpecRendererProps) {
  const tabs = React.useMemo(() => {
    const declared = spec.tabs?.length ? spec.tabs : ["Overview"];
    const extra = Array.from(new Set(spec.widgets.map((w) => w.tab || "Overview"))).filter((t) => !declared.includes(t));
    return [...declared, ...extra].filter((t) => spec.widgets.some((w) => (w.tab || "Overview") === t));
  }, [spec]);
  const [tab, setTab] = React.useState(tabs[0] ?? "Overview");
  React.useEffect(() => {
    if (!tabs.includes(tab)) setTab(tabs[0] ?? "Overview");
  }, [tabs, tab]);

  const [filterValues, setFilterValues] = React.useState<FilterValues>({});
  const filters = React.useMemo(
    () =>
      (spec.filters ?? [])
        .map((f) => ({ f, options: filterOptions(results, f) }))
        .filter((x) => x.options.length > 0),
    [spec.filters, results],
  );

  // Ready tracking: every rendered widget reports once.
  const renderedIds = React.useMemo(
    () => spec.widgets.filter((w) => allTabs || (w.tab || "Overview") === tab).map((w) => w.id),
    [spec.widgets, allTabs, tab],
  );
  const readySet = React.useRef(new Set<string>());
  const firedRef = React.useRef(false);
  const onReadyRef = React.useRef(onReady);
  onReadyRef.current = onReady;
  const check = React.useCallback(() => {
    if (firedRef.current) return;
    if (renderedIds.every((id) => readySet.current.has(id))) {
      firedRef.current = true;
      // give Plotly a moment to finish its final layout pass (setTimeout, not rAF: rAF is paused in hidden tabs)
      setTimeout(() => onReadyRef.current?.(), 150);
    }
  }, [renderedIds]);
  const markReady = React.useCallback(
    (id: string) => {
      readySet.current.add(id);
      check();
    },
    [check],
  );
  React.useEffect(() => {
    check();
  }, [check]);

  const byTab = (t: string) => spec.widgets.filter((w) => (w.tab || "Overview") === t);
  const activeFilters = Object.values(filterValues).filter(Boolean).length;

  const filterBar = filters.length > 0 && (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-3">
      <div className="flex items-center gap-1.5 self-center text-xs font-medium text-muted-foreground">
        <FilterIcon className="size-3.5" aria-hidden /> Filters
      </div>
      {filters.map(({ f, options }) => (
        <label key={f.id} className="flex min-w-36 flex-col gap-1 text-xs">
          <span className="text-muted-foreground">{f.label}</span>
          <Select
            value={filterValues[f.id] ?? ""}
            onChange={(e) => setFilterValues((v) => ({ ...v, [f.id]: e.target.value }))}
            className="h-8 text-xs"
          >
            <option value="">All</option>
            {options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </Select>
        </label>
      ))}
      {activeFilters > 0 && (
        <button
          type="button"
          onClick={() => setFilterValues({})}
          className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="size-3.5" aria-hidden /> Clear
        </button>
      )}
    </div>
  );

  const gridProps = { results, spec, filterValues, onReady: markReady };

  if (allTabs || tabs.length <= 1) {
    return (
      <div className={className}>
        {filterBar}
        <div className="space-y-8">
          {tabs.map((t) => (
            <div key={t} data-tab={t}>
              {tabs.length > 1 && <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{t}</h2>}
              <Grid widgets={byTab(t)} {...gridProps} />
            </div>
          ))}
          {tabs.length === 0 && <WidgetEmpty message="This dashboard has no widgets." />}
        </div>
      </div>
    );
  }

  return (
    <Tabs value={tab} onValueChange={setTab} className={className}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <TabsList aria-label="Dashboard tabs">
          {tabs.map((t) => (
            <TabsTrigger key={t} value={t}>
              {t}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      {filterBar}
      {tabs.map((t) => (
        <TabsContent key={t} value={t}>
          <Grid widgets={byTab(t)} {...gridProps} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
